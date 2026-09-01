import json

import pytest
from alembic import command
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.config import Settings
from app.core.database import Base
from app.core.migration_state import alembic_config
from app.models import AuditLog, Business, BusinessUser, User
from app.routers.channel_onboarding import (
    approve_owner_channel_connection,
    get_business_channel_onboarding,
    grant_owner_channel_access,
    request_business_channel_connection,
    stop_owner_channel_access,
    update_owner_channel_capabilities,
)
from app.schemas.channel_onboarding import (
    ChannelAccessGrantRequest,
    ChannelCapabilitiesUpdate,
    ChannelDecisionRequest,
    SimulatedConnectionRequest,
)
from app.services.capability_service import configure_business_modules
from app.services.channel_control_service import (
    channel_automation_is_authorized,
    get_channel_control,
    integrated_delivery_is_authorized,
)


@pytest.fixture
def db(monkeypatch):
    test_settings = Settings(
        _env_file=None,
        app_env="test",
        instagram_simulated_onboarding_test_only=True,
    )
    monkeypatch.setattr(
        "app.services.channel_control_service.get_settings", lambda: test_settings
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def channel_context(db):
    business = Business(slug="channel-a", name="Channel A", status="active")
    other = Business(slug="channel-b", name="Channel B", status="active")
    owner = User(email="owner@channels.test", is_owner=True)
    admin = User(email="admin@channels.test")
    staff = User(email="staff@channels.test")
    other_admin = User(email="other@channels.test")
    db.add_all([business, other, owner, admin, staff, other_admin])
    db.flush()
    for configured_business in (business, other):
        configure_business_modules(
            db,
            business_id=configured_business.id,
            enabled_modules=("essential", "growth", "social"),
            actor_user_id=owner.id,
        )
    db.add_all(
        [
            BusinessUser(
                business_id=business.id,
                user_id=admin.id,
                role="business_admin",
                active=True,
            ),
            BusinessUser(
                business_id=business.id,
                user_id=staff.id,
                role="business_staff",
                active=True,
            ),
            BusinessUser(
                business_id=other.id,
                user_id=other_admin.id,
                role="business_admin",
                active=True,
            ),
        ]
    )
    db.commit()
    return business, other, owner, admin, staff, other_admin


def http_request(method="POST"):
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/channel-onboarding/test",
            "headers": [(b"x-request-id", b"channel-control-test")],
            "client": ("testclient", 50000),
        }
    )


def grant(db, business, owner, *, channel="instagram", policy="business_admin"):
    return grant_owner_channel_access(
        business.id,
        channel,
        ChannelAccessGrantRequest(
            connector_policy=policy,
            reason="Canal incluido en el contrato",
        ),
        http_request("PUT"),
        actor=owner,
        db=db,
    )


def request_connection(db, business, admin, *, channel="instagram"):
    return request_business_channel_connection(
        business.slug,
        channel,
        SimulatedConnectionRequest(confirm_meta_authority=True),
        http_request(),
        actor=admin,
        db=db,
    )


def approve(db, business, owner, *, channel="instagram"):
    return approve_owner_channel_connection(
        business.id,
        channel,
        ChannelDecisionRequest(reason="Activos revisados por operaciones"),
        http_request(),
        actor=owner,
        db=db,
    )


def test_guided_request_requires_owner_grant_and_becomes_pending(db, channel_context):
    business, _other, owner, admin, _staff, _other_admin = channel_context
    initial = get_business_channel_onboarding(business.slug, actor=admin, db=db)
    assert {item["status"] for item in initial["channels"]} == {"not_allowed"}
    assert initial["accepts_credentials"] is False

    granted = grant(db, business, owner)
    assert granted["status"] == "available"
    assert granted["can_request"] is True
    requested = request_connection(db, business, admin)
    assert requested["status"] == "pending_approval"
    assert requested["integrated_delivery_enabled"] is False
    assert requested["automation_enabled"] is False

    audit = db.query(AuditLog).filter_by(action="channel_connection_requested").one()
    metadata = json.loads(audit.metadata_json)
    assert metadata["connection_mode"] == "simulated"
    assert "token" not in audit.metadata_json.lower()
    assert "external_account" not in audit.metadata_json.lower()
    client_view = get_business_channel_onboarding(business.slug, actor=admin, db=db)
    instagram = next(item for item in client_view["channels"] if item["channel"] == "instagram")
    assert instagram["last_reason"] is None


def test_channel_control_reasons_reject_whitespace():
    for schema, payload in (
        (ChannelAccessGrantRequest, {"connector_policy": "business_admin", "reason": "   "}),
        (ChannelDecisionRequest, {"reason": "   "}),
        (ChannelCapabilitiesUpdate, {"automation_enabled": True, "reason": "   "}),
    ):
        with pytest.raises(ValidationError):
            schema.model_validate(payload)


def test_approval_does_not_enable_delivery_or_automation(db, channel_context):
    business, _other, owner, admin, _staff, _other_admin = channel_context
    grant(db, business, owner)
    request_connection(db, business, admin)
    approved = approve(db, business, owner)
    assert approved["status"] == "approved"
    assert approved["integrated_delivery_enabled"] is False
    assert approved["automation_enabled"] is False
    assert not integrated_delivery_is_authorized(db, business_id=business.id, channel="instagram")
    assert not channel_automation_is_authorized(db, business_id=business.id, channel="instagram")

    enabled = update_owner_channel_capabilities(
        business.id,
        "instagram",
        ChannelCapabilitiesUpdate(
            integrated_delivery_enabled=True,
            automation_enabled=False,
            reason="Activación operativa gradual",
        ),
        http_request("PATCH"),
        actor=owner,
        db=db,
    )
    assert enabled["integrated_delivery_enabled"] is True
    assert enabled["automation_enabled"] is False
    assert integrated_delivery_is_authorized(db, business_id=business.id, channel="instagram")
    assert not channel_automation_is_authorized(db, business_id=business.id, channel="instagram")


def test_suspend_and_revoke_disable_both_capabilities(db, channel_context):
    business, _other, owner, admin, _staff, _other_admin = channel_context
    grant(db, business, owner, channel="whatsapp")
    request_connection(db, business, admin, channel="whatsapp")
    approve(db, business, owner, channel="whatsapp")
    update_owner_channel_capabilities(
        business.id,
        "whatsapp",
        ChannelCapabilitiesUpdate(
            integrated_delivery_enabled=True,
            automation_enabled=True,
            reason="Canal listo para producción",
        ),
        http_request("PATCH"),
        actor=owner,
        db=db,
    )
    suspended = stop_owner_channel_access(
        business.id,
        "whatsapp",
        "suspend",
        ChannelDecisionRequest(reason="Incidencia contractual abierta"),
        http_request(),
        actor=owner,
        db=db,
    )
    assert suspended["status"] == "suspended"
    assert suspended["integrated_delivery_enabled"] is False
    assert suspended["automation_enabled"] is False

    grant(db, business, owner, channel="whatsapp")
    request_connection(db, business, admin, channel="whatsapp")
    approve(db, business, owner, channel="whatsapp")
    revoked = stop_owner_channel_access(
        business.id,
        "whatsapp",
        "revoke",
        ChannelDecisionRequest(reason="Acceso retirado por el Owner"),
        http_request(),
        actor=owner,
        db=db,
    )
    assert revoked["status"] == "revoked"
    assert not integrated_delivery_is_authorized(db, business_id=business.id, channel="whatsapp")
    assert not channel_automation_is_authorized(db, business_id=business.id, channel="whatsapp")


def test_connector_policy_and_tenant_isolation_are_enforced(db, channel_context):
    business, _other, owner, admin, staff, other_admin = channel_context
    grant(db, business, owner, policy="owner_only")
    with pytest.raises(HTTPException) as denied_policy:
        request_connection(db, business, admin)
    assert denied_policy.value.status_code == 403

    for actor in (staff, other_admin):
        with pytest.raises(HTTPException) as denied_tenant:
            get_business_channel_onboarding(business.slug, actor=actor, db=db)
        assert denied_tenant.value.status_code == 403

    control = get_channel_control(db, business_id=business.id, channel="instagram")
    assert control is not None
    assert control.business_id == business.id


def test_migration_backfills_existing_connected_integration_and_downgrades(tmp_path):
    database_path = tmp_path / "channel-controls.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = database_url
    command.upgrade(config, "20260730_06")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO businesses (slug, name, status, country_code, language_code, "
                "timezone, currency, seo_noindex, created_at, updated_at) VALUES "
                "('legacy-channel', 'Legacy channel', 'active', 'ES', 'es', "
                "'Europe/Madrid', 'EUR', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        business_id = connection.execute(
            text("SELECT id FROM businesses WHERE slug = 'legacy-channel'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO business_channel_integrations "
                "(business_id, channel, provider, external_account_id, integration_status, "
                "created_at, updated_at) VALUES "
                "(:business_id, 'whatsapp', 'whatsapp', '123456789012345', 'connected', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"business_id": business_id},
        )
    engine.dispose()

    command.upgrade(config, "head")
    migrated = create_engine(database_url)
    with migrated.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT status, connector_policy, connection_mode, "
                    "integrated_delivery_enabled, automation_enabled "
                    "FROM business_channel_controls WHERE business_id = :business_id"
                ),
                {"business_id": business_id},
            )
            .mappings()
            .one()
        )
        assert row["status"] == "approved"
        assert row["connector_policy"] == "owner_only"
        assert row["connection_mode"] == "legacy"
        assert bool(row["integrated_delivery_enabled"])
        assert not bool(row["automation_enabled"])
    migrated.dispose()

    command.downgrade(config, "20260730_06")
    downgraded = create_engine(database_url)
    assert "business_channel_controls" not in inspect(downgraded).get_table_names()
    downgraded.dispose()
