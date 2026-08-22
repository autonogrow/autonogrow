from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.core.database import Base
from app.core.migration_state import alembic_config
from app.models import (
    AuditLog,
    AvailabilitySettings,
    Booking,
    BookingAttribution,
    Business,
    BusinessModuleAccess,
    BusinessService,
    BusinessUser,
    Customer,
    CustomerOpportunity,
    OpportunityAction,
    PilotBaseline,
    User,
)
from app.routers.pilot_operations import patch_owner_module
from app.schemas.pilot import ModuleAccessUpdate
from app.services.business_readiness_service import evaluate_business_readiness
from app.services.capability_service import (
    configure_business_modules,
    module_capabilities,
    require_growth_access,
    require_social_access,
)
from app.services.growth_opportunity_service import GrowthOpportunityService
from app.services.pilot_value_service import pilot_value_summary
from app.services.social_content_intelligence_service import SocialContentIntelligenceService

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": "/api/owner/businesses/1/modules/growth",
            "headers": [],
            "client": ("test", 1234),
        }
    )


def test_module_combinations_are_authoritative_and_essential_is_required(db: Session):
    owner = User(email="owner-modules@test.local", is_owner=True)
    businesses = [
        Business(name="A", slug="module-a"),
        Business(name="B", slug="module-b"),
        Business(name="C", slug="module-c"),
    ]
    db.add_all([owner, *businesses])
    db.flush()
    configure_business_modules(
        db,
        business_id=businesses[0].id,
        enabled_modules=["essential", "social"],
        actor_user_id=owner.id,
    )
    configure_business_modules(
        db,
        business_id=businesses[1].id,
        enabled_modules=["essential", "growth"],
        actor_user_id=owner.id,
    )
    configure_business_modules(
        db,
        business_id=businesses[2].id,
        enabled_modules=["essential", "growth", "social"],
        actor_user_id=owner.id,
    )
    db.commit()

    assert {key: value["available"] for key, value in module_capabilities(db, businesses[0].id).items()} == {
        "essential": True,
        "growth": False,
        "social": True,
    }
    assert not module_capabilities(db, businesses[1].id)["social"]["available"]
    assert all(value["available"] for value in module_capabilities(db, businesses[2].id).values())
    db.query(BusinessModuleAccess).filter_by(
        business_id=businesses[2].id, module_key="social"
    ).delete()
    assert module_capabilities(db, businesses[2].id)["social"]["configuration_source"] == (
        "missing_configuration"
    )
    assert module_capabilities(db, businesses[2].id)["social"]["available"] is False
    with pytest.raises(ValueError, match="essential_is_required"):
        from app.services.capability_service import update_business_module

        update_business_module(
            db,
            business_id=businesses[0].id,
            module_key="essential",
            entitled=False,
            active=False,
            module_cost_amount=None,
            module_cost_currency=None,
            actor_user_id=owner.id,
        )


def test_disabled_module_blocks_api_stops_generation_and_preserves_data(db: Session):
    owner = User(email="owner-enforcement@test.local", is_owner=True)
    business = Business(name="Enforcement", slug="module-enforcement", status="active")
    customer = Customer(business=business, name="Customer", phone="+34600000010")
    db.add_all([owner, business, customer])
    db.flush()
    configure_business_modules(
        db,
        business_id=business.id,
        enabled_modules=["essential"],
        actor_user_id=owner.id,
    )
    opportunity = CustomerOpportunity(
        business_id=business.id,
        customer_id=customer.id,
        type="lead_not_converted",
        detected_at=NOW,
        due_at=NOW,
        reason_code="test",
        reason_text="Existing historical data",
        dedupe_key="preserved-growth-data",
    )
    db.add(opportunity)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        require_growth_access(business.slug, owner, db)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "module_not_available"
    with pytest.raises(HTTPException) as social_exc:
        require_social_access(business.slug, owner, db)
    assert social_exc.value.status_code == 403
    assert GrowthOpportunityService(db, now=NOW).evaluate_business(business.id).created == 0
    assert SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id).created == 0
    assert db.get(CustomerOpportunity, opportunity.id) is not None

    result = patch_owner_module(
        business.id,
        "growth",
        ModuleAccessUpdate(
            entitled=True,
            active=True,
            reason="Reactivar para continuar el piloto",
        ),
        request(),
        owner,
        db,
    )
    assert result["module"]["available"] is True
    assert db.get(CustomerOpportunity, opportunity.id) is not None
    assert db.query(AuditLog).filter(AuditLog.action == "business_module_access_updated").count() == 1


def test_readiness_separates_booking_pilot_and_optional_modules(db: Session):
    owner = User(email="owner-readiness@test.local", is_owner=True)
    admin = User(email="admin-readiness@test.local")
    business = Business(
        name="Ready",
        slug="pilot-ready",
        status="active",
        phone="+34600000011",
    )
    db.add_all([owner, admin, business])
    db.flush()
    db.add(
        BusinessUser(
            business_id=business.id,
            user_id=admin.id,
            role="business_admin",
            active=True,
        )
    )
    db.add(BusinessService(business_id=business.id, name="Service", duration_minutes=30))
    db.add(
        AvailabilitySettings(
            business_id=business.id,
            weekly_schedule_json=json.dumps({"1": [{"start": "09:00", "end": "17:00"}]}),
        )
    )
    configure_business_modules(
        db,
        business_id=business.id,
        enabled_modules=["essential", "growth"],
        actor_user_id=owner.id,
    )
    db.commit()

    result = evaluate_business_readiness(db, business)
    assert result["booking_ready"] is True
    assert result["pilot_ready"] is True
    assert result["modules"]["social"]["status"] == "disabled"
    assert "social_action_required" not in result["warnings"]
    assert "no_verified_environment_backup" in result["warnings"]


def test_value_is_separated_by_module_and_roi_uses_only_direct_attribution(db: Session):
    owner = User(email="owner-value@test.local", is_owner=True)
    business = Business(name="Value", slug="pilot-value", status="active", currency="EUR")
    other = Business(name="Other", slug="pilot-value-other", status="active", currency="EUR")
    db.add_all([owner, business, other])
    db.flush()
    configure_business_modules(
        db,
        business_id=business.id,
        enabled_modules=["essential", "growth"],
        actor_user_id=owner.id,
    )
    configure_business_modules(
        db,
        business_id=other.id,
        enabled_modules=["essential"],
        actor_user_id=owner.id,
    )
    growth_access = (
        db.query(BusinessModuleAccess)
        .filter_by(business_id=business.id, module_key="growth")
        .one()
    )
    growth_access.module_cost_amount = Decimal("20.00")
    growth_access.module_cost_currency = "EUR"
    customer = Customer(business_id=business.id, name="Ana", phone="+34600000012")
    service = BusinessService(
        business_id=business.id,
        name="Service",
        duration_minutes=30,
        price_amount=Decimal("60.00"),
    )
    db.add_all([customer, service])
    db.flush()
    booking = Booking(
        business_id=business.id,
        customer_id=customer.id,
        service_id=service.id,
        service_name=service.name,
        preferred_time="10:00",
        status="completed",
        source="landing",
        price_amount_snapshot=Decimal("60.00"),
        currency_snapshot="EUR",
        created_at=(NOW - timedelta(days=2)).replace(tzinfo=None),
    )
    opportunity = CustomerOpportunity(
        business_id=business.id,
        customer_id=customer.id,
        type="service_due",
        status="resolved",
        detected_at=NOW - timedelta(days=5),
        due_at=NOW - timedelta(days=4),
        reason_code="due",
        reason_text="Service due",
        dedupe_key="value-opportunity",
    )
    db.add_all([booking, opportunity])
    db.flush()
    action = OpportunityAction(
        business_id=business.id,
        opportunity_id=opportunity.id,
        customer_id=customer.id,
        action_type="contact_customer",
        status="completed",
        sent_at=NOW - timedelta(days=3),
        completed_at=NOW - timedelta(days=2),
        created_at=NOW - timedelta(days=4),
    )
    db.add(action)
    db.flush()
    db.add(
        BookingAttribution(
            business_id=business.id,
            opportunity_id=opportunity.id,
            action_id=action.id,
            booking_id=booking.id,
            method="direct_link",
            price_amount_snapshot=Decimal("60.00"),
            currency_snapshot="EUR",
            attributed_at=NOW - timedelta(days=2),
            completed_at=NOW - timedelta(days=1),
        )
    )
    db.add(
        PilotBaseline(
            business_id=business.id,
            monthly_bookings=0,
            average_ticket=Decimal("50.00"),
            currency="EUR",
            updated_by_user_id=owner.id,
        )
    )
    db.commit()

    result = pilot_value_summary(db, business=business, period="30d", now=NOW)
    assert result["modules"]["essential"]["metrics"]["managed_booking_value"]["amount"] == "60.00"
    assert result["modules"]["essential"]["directly_attributable_revenue"] is None
    assert result["modules"]["growth"]["directly_attributable_revenue"]["amount"] == "60.00"
    assert result["modules"]["growth"]["roi"]["roi_percentage"] == "200.00"
    assert result["modules"]["social"]["state"] == "disabled"
    assert result["modules"]["social"]["metrics"] is None
    assert result["modules"]["social"]["roi"]["status"] == "not_active"
    assert result["baseline_comparison"]["causal_claim"] is False
    assert result["baseline_comparison"]["label"] == "Variación durante el piloto"

    growth_access.module_cost_amount = Decimal("0")
    db.commit()
    assert pilot_value_summary(db, business=business, period="30d", now=NOW)["modules"][
        "growth"
    ]["roi"]["status"] == "unavailable_zero_cost"
    growth_access.module_cost_amount = None
    growth_access.module_cost_currency = None
    db.commit()
    assert pilot_value_summary(db, business=business, period="30d", now=NOW)["modules"][
        "growth"
    ]["roi"]["status"] == "unavailable_no_cost"

    isolated = pilot_value_summary(db, business=other, period="30d", now=NOW)
    assert isolated["modules"]["essential"]["metrics"]["bookings_managed"] == 0
    assert isolated["modules"]["growth"]["state"] == "disabled"


def test_pilot_migration_upgrade_and_downgrade(tmp_path):
    path = tmp_path / "pilot-modules.db"
    config = alembic_config()
    config.attributes["database_url"] = f"sqlite:///{path.as_posix()}"
    command.upgrade(config, "20260821_22")
    command.upgrade(config, "20260822_23")
    engine = create_engine(config.attributes["database_url"])
    assert {"business_module_access", "pilot_baselines"} <= set(inspect(engine).get_table_names())
    engine.dispose()
    command.downgrade(config, "20260821_22")
    engine = create_engine(config.attributes["database_url"])
    assert "business_module_access" not in inspect(engine).get_table_names()
    assert "pilot_baselines" not in inspect(engine).get_table_names()
    engine.dispose()
