import json

import pytest
from alembic import command
from fastapi import HTTPException
from pydantic import ValidationError
from scripts.seed_onboarding_templates import seed_templates
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.database import Base
from app.core.migration_state import alembic_config
from app.models import (
    AuditLog,
    AutomationCreditTransaction,
    AvailabilitySettings,
    Business,
    BusinessOnboardingSession,
    BusinessOnboardingTemplate,
    BusinessService,
    Customer,
    User,
)
from app.routers.owner_onboarding import (
    activate_business,
    archive_business,
    preview_business,
    reactivate_business,
    suspend_business,
)
from app.schemas.onboarding import (
    ActivationRequest,
    BookingRulesStepRequest,
    BusinessStateReasonRequest,
    ContactStepRequest,
    OnboardingStartRequest,
    SchedulesStepRequest,
    ServicesStepRequest,
)
from app.services.business_onboarding_service import (
    apply_template,
    clone_configuration,
    initialize_plan,
    mark_step_saved,
    normalize_onboarding_slug,
    transition_business,
    validate_placeholders,
)
from app.services.business_readiness_service import evaluate_business_readiness
from app.services.onboarding_template_catalog import (
    SYSTEM_ONBOARDING_TEMPLATES,
    template_has_forbidden_data,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def owner(db):
    row = User(email="onboarding-owner@test.local", is_owner=True)
    db.add(row)
    db.commit()
    return row


def business_session(db, owner, *, slug="new-business"):
    business = Business(name="New business", slug=slug, status="onboarding")
    db.add(business)
    db.flush()
    onboarding = BusinessOnboardingSession(
        business_id=business.id,
        started_by_user_id=owner.id,
        last_updated_by_user_id=owner.id,
    )
    db.add(onboarding)
    db.commit()
    return business, onboarding


def request(path="/api/owner/test"):
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"x-request-id", b"onboarding-test")],
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 123),
        }
    )


def make_ready(db, business):
    db.add(BusinessService(business_id=business.id, name="Bookable", duration_minutes=30))
    db.add(
        AvailabilitySettings(
            business_id=business.id,
            weekly_schedule_json=json.dumps({"1": [{"start": "09:00", "end": "17:00"}]}),
        )
    )
    db.commit()


def system_template(db, key="generic"):
    definition = next(item for item in SYSTEM_ONBOARDING_TEMPLATES if item["key"] == key)
    row = BusinessOnboardingTemplate(
        key=definition["key"],
        name=definition["name"],
        category=definition["category"],
        description=definition["description"],
        version=definition["version"],
        is_active=True,
        is_system=True,
        configuration_json=json.dumps(definition["configuration"]),
    )
    db.add(row)
    db.commit()
    return row


def test_session_is_persistent_partial_and_resumable(db, owner):
    _business, onboarding = business_session(db, owner)
    mark_step_saved(
        onboarding,
        step="business_identity",
        actor_user_id=owner.id,
        completed=True,
        summary={"identity_complete": True},
    )
    db.commit()
    db.expire_all()
    resumed = db.get(BusinessOnboardingSession, onboarding.id)
    assert "business_identity" in json.loads(resumed.completed_steps_json)
    assert resumed.current_step == "contact_and_location"
    assert str(owner.id) in resumed.step_activity_json


def test_only_one_active_session_per_business(db, owner):
    business, _session = business_session(db, owner)
    db.add(
        BusinessOnboardingSession(
            business_id=business.id,
            started_by_user_id=owner.id,
            last_updated_by_user_id=owner.id,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_strict_schemas_reject_extra_and_unsafe_values():
    with pytest.raises(ValidationError):
        OnboardingStartRequest(name="A business", status="active")
    with pytest.raises(ValidationError):
        ContactStepRequest(maps_url="javascript:alert(1)")
    with pytest.raises(ValidationError):
        ServicesStepRequest(
            services=[{"name": "Invalid", "duration_minutes": 0, "price_amount": -1}]
        )
    with pytest.raises(ValidationError):
        SchedulesStepRequest(
            weekly_schedule={
                "1": [
                    {"start": "09:00", "end": "12:00"},
                    {"start": "11:00", "end": "13:00"},
                ]
            }
        )
    with pytest.raises(ValidationError):
        BookingRulesStepRequest(
            min_notice_minutes=2000,
            max_days_ahead=1,
            slot_interval_minutes=15,
        )


def test_slug_and_placeholder_validation():
    assert normalize_onboarding_slug("Clínica Norte") == "clinica-norte"
    with pytest.raises(ValueError):
        normalize_onboarding_slug("owner")
    validate_placeholders("Hola {{customer_name}} en {{business_name}}")
    with pytest.raises(ValueError):
        validate_placeholders("{{__class__}}")


def test_template_apply_is_idempotent_and_rows_are_independent(db, owner):
    template = system_template(db, "barbershop")
    first_business, first_session = business_session(db, owner, slug="first-template")
    second_business, second_session = business_session(db, owner, slug="second-template")
    first = apply_template(
        db,
        business=first_business,
        session=first_session,
        template=template,
        actor_user_id=owner.id,
        retain_existing=True,
    )
    again = apply_template(
        db,
        business=first_business,
        session=first_session,
        template=template,
        actor_user_id=owner.id,
        retain_existing=True,
    )
    apply_template(
        db,
        business=second_business,
        session=second_session,
        template=template,
        actor_user_id=owner.id,
        retain_existing=True,
    )
    db.commit()
    first_rows = db.query(BusinessService).filter_by(business_id=first_business.id).all()
    second_rows = db.query(BusinessService).filter_by(business_id=second_business.id).all()
    assert first["services"] > 0 and again["services"] == 0
    assert len(first_rows) == len(second_rows)
    assert {row.id for row in first_rows}.isdisjoint({row.id for row in second_rows})


def test_template_catalog_has_no_secret_fields():
    assert len(SYSTEM_ONBOARDING_TEMPLATES) == 6
    assert all(not template_has_forbidden_data(item) for item in SYSTEM_ONBOARDING_TEMPLATES)


def test_clone_copies_configuration_but_not_tenant_data(db, owner):
    source = Business(name="Source", slug="clone-source", status="active")
    target, _session = business_session(db, owner, slug="clone-target")
    db.add(source)
    db.flush()
    db.add_all(
        [
            BusinessService(business_id=source.id, name="Service", duration_minutes=30),
            AvailabilitySettings(
                business_id=source.id,
                weekly_schedule_json=json.dumps({"1": [{"start": "09:00", "end": "17:00"}]}),
            ),
            Customer(business_id=source.id, name="Private customer", phone="600000000"),
        ]
    )
    db.flush()
    result = clone_configuration(
        db, source=source, target=target, sections=["services", "schedules"]
    )
    db.commit()
    assert result["created_services"] == 1
    assert db.query(BusinessService).filter_by(business_id=target.id).count() == 1
    assert db.query(AvailabilitySettings).filter_by(business_id=target.id).count() == 1
    assert db.query(Customer).filter_by(business_id=target.id).count() == 0


def test_readiness_reports_blockers_warnings_and_optional_integration(db, owner):
    business, _session = business_session(db, owner, slug="readiness-empty")
    result = evaluate_business_readiness(db, business)
    keyed = {item["key"]: item for item in result["checks"]}
    assert not result["ready"]
    assert keyed["services"]["blocking"]
    assert keyed["schedules"]["blocking"]
    assert keyed["integrations"]["status"] == "warning"
    assert not keyed["integrations"]["blocking"]


def test_ready_business_passes_without_optional_integration(db, owner):
    business, _session = business_session(db, owner, slug="readiness-complete")
    make_ready(db, business)
    result = evaluate_business_readiness(db, business)
    assert result["ready"]
    assert result["blocking_count"] == 0
    assert result["warning_count"] > 0


def test_preview_is_non_operational_and_archived_is_rejected(db, owner):
    business, _session = business_session(db, owner, slug="private-preview")
    db.add(BusinessService(business_id=business.id, name="Preview", duration_minutes=30))
    db.commit()
    result = preview_business(business.id, db)
    assert result["robots"] == "noindex,nofollow"
    assert result["booking_mode"] == "disabled"
    assert result["automations_enabled"] is False
    assert result["credits_consumed"] is False
    business.status = "archived"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        preview_business(business.id, db)
    assert exc.value.status_code == 409


def test_plan_wallet_period_and_ledger_are_idempotent(db, owner):
    business, _session = business_session(db, owner, slug="plan-idempotent")
    first_settings, first_tx = initialize_plan(
        db,
        business=business,
        plan_key="starter",
        included_credits=100,
        additional_credits=25,
        period_days=30,
        actor_user_id=owner.id,
    )
    db.commit()
    second_settings, second_tx = initialize_plan(
        db,
        business=business,
        plan_key="starter",
        included_credits=100,
        additional_credits=25,
        period_days=30,
        actor_user_id=owner.id,
    )
    assert first_settings.id == second_settings.id
    assert first_tx.id == second_tx.id
    assert db.query(AutomationCreditTransaction).filter_by(business_id=business.id).count() == 1
    assert second_settings.period_started_at and second_settings.period_ends_at


def test_incomplete_business_cannot_activate(db, owner):
    business, _session = business_session(db, owner, slug="cannot-activate")
    readiness = evaluate_business_readiness(db, business)
    with pytest.raises(HTTPException) as exc:
        activate_business(
            business.id,
            ActivationRequest(
                reason="Owner review complete",
                expected_readiness_version=readiness["version"],
            ),
            request(),
            owner,
            db,
        )
    assert exc.value.status_code == 409
    assert db.get(Business, business.id).status == "onboarding"


def test_activation_is_audited_idempotent_and_completes_session(db, owner):
    business, onboarding = business_session(db, owner, slug="activate-ready")
    make_ready(db, business)
    readiness = evaluate_business_readiness(db, business)
    result = activate_business(
        business.id,
        ActivationRequest(
            reason="Owner review complete",
            expected_readiness_version=readiness["version"],
        ),
        request(),
        owner,
        db,
    )
    assert result["business"]["status"] == "active"
    assert db.get(BusinessOnboardingSession, onboarding.id).status == "completed"
    assert {
        row.action for row in db.query(AuditLog).filter(AuditLog.business_id == business.id).all()
    } >= {"business_activated", "business_onboarding_completed"}
    repeated = activate_business(
        business.id,
        ActivationRequest(
            reason="Repeated safe request",
            expected_readiness_version=readiness["version"],
        ),
        request(),
        owner,
        db,
    )
    assert repeated["already_active"] is True


def test_suspend_reactivate_archive_preserve_data_and_block_restore(db, owner):
    business, _session = business_session(db, owner, slug="state-operations")
    make_ready(db, business)
    business.status = "ready"
    db.commit()
    transition_business(business, "active")
    db.commit()
    reason = BusinessStateReasonRequest(reason="Owner operational decision")
    suspend_business(business.id, reason, request(), owner, db)
    assert db.get(Business, business.id).status == "suspended"
    assert db.query(BusinessService).filter_by(business_id=business.id).count() == 1
    reactivated = reactivate_business(business.id, reason, request(), owner, db)
    assert reactivated["business"]["status"] == "active"
    assert db.get(Business, business.id).status == "active"
    suspend_business(business.id, reason, request(), owner, db)
    archive_business(business.id, reason, request(), owner, db)
    assert db.get(Business, business.id).status == "archived"
    with pytest.raises(HTTPException) as exc:
        reactivate_business(business.id, reason, request(), owner, db)
    assert exc.value.status_code == 409


def test_state_machine_blocks_archived_reactivation():
    business = Business(name="State", slug="state-machine", status="draft")
    transition_business(business, "onboarding")
    transition_business(business, "ready")
    transition_business(business, "active")
    transition_business(business, "suspended")
    transition_business(business, "archived")
    with pytest.raises(ValueError):
        transition_business(business, "active")


def test_seed_is_dry_run_and_idempotent(db):
    factory = sessionmaker(bind=db.get_bind())
    dry = seed_templates(apply=False, session_factory=factory)
    assert dry["created"] == 6
    assert db.query(BusinessOnboardingTemplate).count() == 0
    applied = seed_templates(apply=True, session_factory=factory)
    repeated = seed_templates(apply=True, session_factory=factory)
    assert applied["created"] == 6
    assert repeated["unchanged"] == 6
    assert db.query(BusinessOnboardingTemplate).count() == 6


def test_migration_05_upgrade_downgrade_and_business_backfill(tmp_path):
    path = tmp_path / "onboarding-migration.db"
    config = alembic_config()
    config.attributes["database_url"] = f"sqlite:///{path.as_posix()}"
    command.upgrade(config, "20260730_04")
    engine = create_engine(config.attributes["database_url"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO businesses (slug, name, status, created_at, updated_at) "
                "VALUES ('existing-active', 'Existing active', 'active', CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP)"
            )
        )
    engine.dispose()
    command.upgrade(config, "20260730_05")
    engine = create_engine(config.attributes["database_url"])
    assert "business_onboarding_sessions" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT status FROM businesses")).scalar_one() == "active"
    engine.dispose()
    command.downgrade(config, "20260730_04")
    engine = create_engine(config.attributes["database_url"])
    assert "business_onboarding_sessions" not in inspect(engine).get_table_names()
    engine.dispose()
    command.upgrade(config, "20260730_05")
