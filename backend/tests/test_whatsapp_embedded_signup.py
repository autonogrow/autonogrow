import base64
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.core.migration_state import alembic_config
from app.middleware.rate_limit import RateLimitMiddleware
from app.models import (
    Business,
    BusinessChannelControl,
    BusinessChannelIntegration,
    BusinessUser,
    Conversation,
    User,
)
from app.services.channel_control_service import request_simulated_connection
from app.services.integration_crypto_service import decrypt_secret, encrypt_secret
from app.services.whatsapp_embedded_signup_provider import (
    WHATSAPP_EMBEDDED_SIGNUP_SCOPES,
    WhatsAppBusinessToken,
    WhatsAppEmbeddedSignupProviderError,
    WhatsAppVerifiedAssets,
    inspect_whatsapp_business_token,
    verify_whatsapp_embedded_signup_assets,
)
from app.services.whatsapp_embedded_signup_service import (
    complete_whatsapp_embedded_signup,
    decide_whatsapp_signup_candidate,
    retry_whatsapp_candidate_setup,
    serialize_whatsapp_signup_attempt,
    start_whatsapp_embedded_signup,
)

META_BUSINESS_ID = "100000000001"
WABA_ID = "200000000002"
PHONE_ID = "300000000003"


def signup_settings(**overrides) -> Settings:
    encryption_key = base64.urlsafe_b64encode(b"W" * 32).decode("ascii")
    values = {
        "app_env": "test",
        "session_secret": "test-session-secret-with-at-least-32-characters",
        "meta_app_id": "400000000004",
        "meta_app_secret": "test-meta-app-secret",
        "whatsapp_embedded_signup_enabled": True,
        "whatsapp_embedded_signup_config_id": "500000000005",
        "whatsapp_embedded_signup_graph_api_version": "v26.0",
        "integration_encryption_keys_json": f'{{"v1":"{encryption_key}"}}',
        "integration_encryption_active_key_version": "v1",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def signup_context(db):
    business = Business(slug="whatsapp-signup", name="WhatsApp Signup", status="active")
    other = Business(slug="other-whatsapp", name="Other WhatsApp", status="active")
    actor = User(email="admin@whatsapp.test", is_active=True)
    owner = User(email="owner@whatsapp.test", is_owner=True, is_active=True)
    db.add_all([business, other, actor, owner])
    db.flush()
    control = BusinessChannelControl(
        business_id=business.id,
        channel="whatsapp",
        status="available",
        connector_policy="business_admin",
        connection_mode="embedded_signup",
        integrated_delivery_enabled=False,
        automation_enabled=False,
        created_by_user_id=owner.id,
        updated_by_user_id=owner.id,
    )
    db.add(control)
    db.add(
        BusinessUser(
            business_id=business.id,
            user_id=actor.id,
            role="business_admin",
            active=True,
        )
    )
    db.commit()
    return business, other, control, actor, owner


def start_attempt(db, signup_context, *, settings=None, purpose=None):
    business, _other, control, actor, _owner = signup_context
    settings = settings or signup_settings()
    attempt, state, public = start_whatsapp_embedded_signup(
        db,
        business=business,
        control=control,
        actor=actor,
        actor_role="business_admin",
        session_token="signed-session-cookie",
        requested_purpose=purpose,
        settings=settings,
    )
    db.commit()
    return attempt, state, public, settings


def success_patches(*, phone_id=PHONE_ID, waba_id=WABA_ID, registration="registered"):
    return (
        patch(
            "app.services.whatsapp_embedded_signup_service.exchange_whatsapp_embedded_signup_code",
            return_value="business-system-user-secret",
        ),
        patch(
            "app.services.whatsapp_embedded_signup_service.inspect_whatsapp_business_token",
            return_value=WhatsAppBusinessToken(
                access_token="business-system-user-secret",
                token_type="business_integration_system_user",
                expires_at=datetime.now(timezone.utc) + timedelta(days=60),
                granted_scopes=WHATSAPP_EMBEDDED_SIGNUP_SCOPES,
            ),
        ),
        patch(
            "app.services.whatsapp_embedded_signup_service.verify_whatsapp_embedded_signup_assets",
            return_value=WhatsAppVerifiedAssets(
                meta_business_id=META_BUSINESS_ID,
                waba_id=waba_id,
                phone_number_id=phone_id,
                verified_name="AutonoGrow Test",
                display_phone_number="+34 612 345 678",
                phone_status="GREEN:VERIFIED:CLOUD_API",
                registration_status=registration,
            ),
        ),
        patch("app.services.whatsapp_embedded_signup_service.subscribe_app_to_whatsapp_waba"),
    )


def complete_candidate(db, state, actor, settings, **asset_overrides):
    patches = success_patches(**asset_overrides)
    with patches[0], patches[1], patches[2], patches[3]:
        return complete_whatsapp_embedded_signup(
            db,
            business_id=actor.business_id if hasattr(actor, "business_id") else 1,
            opaque_state=state,
            authorization_code="single-use-authorization-code",
            event_type="WA_EMBEDDED_SIGNUP",
            event_name="FINISH",
            meta_business_id=META_BUSINESS_ID,
            waba_id=asset_overrides.get("waba_id", WABA_ID),
            phone_number_id=asset_overrides.get("phone_id", PHONE_ID),
            actor=actor,
            session_token="signed-session-cookie",
            settings=settings,
        )


def test_start_hashes_state_and_exposes_only_public_contract(db, signup_context):
    attempt, state, public, _settings = start_attempt(db, signup_context)

    assert len(state) >= 32
    assert attempt.state_hash == hashlib.sha256(state.encode()).hexdigest()
    assert state not in attempt.state_hash
    assert attempt.session_fingerprint_hash != "signed-session-cookie"
    assert attempt.status == "pending"
    assert public == {
        "app_id": "400000000004",
        "config_id": "500000000005",
        "graph_api_version": "v26.0",
        "sdk_url": "https://connect.facebook.net/en_US/sdk.js",
        "event_type": "WA_EMBEDDED_SIGNUP",
        "finish_event": "FINISH",
        "login_parameters": {
            "response_type": "code",
            "override_default_response_type": True,
            "extras": {"setup": {}},
        },
    }
    rendered = repr(public).lower()
    assert "secret" not in rendered
    assert "access_token" not in rendered


def test_disabled_or_incomplete_configuration_fails_at_start_and_simulation_is_closed(
    db, signup_context
):
    business, _other, control, actor, _owner = signup_context
    disabled = signup_settings(whatsapp_embedded_signup_enabled=False)
    with pytest.raises(HTTPException) as unavailable:
        start_whatsapp_embedded_signup(
            db,
            business=business,
            control=control,
            actor=actor,
            actor_role="business_admin",
            session_token="session",
            settings=disabled,
        )
    assert unavailable.value.status_code == 503
    with pytest.raises(HTTPException) as simulation:
        request_simulated_connection(
            db,
            control=control,
            actor=actor,
            actor_role="business_admin",
            settings=signup_settings(),
        )
    assert simulation.value.status_code == 410
    with pytest.raises(ValueError):
        signup_settings(app_env="staging", whatsapp_embedded_signup_test_only=True)
    assert RateLimitMiddleware.policy(
        "/api/admin/businesses/demo/integrations/whatsapp/embedded-signup/complete",
        "POST",
    ) == ("whatsapp-signup-complete", 20, 60)


def test_candidate_is_encrypted_replay_safe_and_owner_approval_keeps_capabilities_off(
    db, signup_context
):
    business, _other, control, actor, owner = signup_context
    _attempt, state, _public, settings = start_attempt(db, signup_context)
    candidate = complete_candidate(db, state, actor, settings)

    assert candidate.status == "candidate_ready"
    assert candidate.candidate_encrypted_access_token != "business-system-user-secret"
    assert (
        decrypt_secret(
            candidate.candidate_encrypted_access_token,
            candidate.candidate_encryption_key_version,
            settings=settings,
        )
        == "business-system-user-secret"
    )
    assert candidate.candidate_display_phone_number_redacted == "•••• 5678"
    assert control.status == "pending_approval"
    assert db.query(BusinessChannelIntegration).count() == 0
    public_candidate = serialize_whatsapp_signup_attempt(candidate)
    assert "candidate_waba_id" not in public_candidate
    assert "candidate_phone_number_id" not in public_candidate
    assert "candidate_encrypted_access_token" not in public_candidate

    with pytest.raises(HTTPException) as replay:
        complete_whatsapp_embedded_signup(
            db,
            business_id=business.id,
            opaque_state=state,
            authorization_code="replayed-code",
            event_type="WA_EMBEDDED_SIGNUP",
            event_name="FINISH",
            meta_business_id=META_BUSINESS_ID,
            waba_id=WABA_ID,
            phone_number_id=PHONE_ID,
            actor=actor,
            session_token="signed-session-cookie",
            settings=settings,
        )
    assert replay.value.status_code == 409

    decided, integration = decide_whatsapp_signup_candidate(
        db,
        business_id=business.id,
        attempt_id=candidate.id,
        actor=owner,
        approve=True,
        reason="Activos revisados",
    )
    db.commit()
    assert decided.status == "approved"
    assert decided.candidate_encrypted_access_token is None
    assert integration is not None
    assert integration.external_account_id == PHONE_ID
    assert integration.provider_account_id == WABA_ID
    assert integration.integration_status == "connected"
    assert (
        decrypt_secret(
            integration.encrypted_access_token,
            integration.encryption_key_version,
            settings=settings,
        )
        == "business-system-user-secret"
    )
    assert control.status == "approved"
    assert not control.integrated_delivery_enabled
    assert not control.automation_enabled


def test_session_mismatch_and_fake_event_do_not_call_meta(db, signup_context):
    business, _other, _control, actor, _owner = signup_context
    attempt, state, _public, settings = start_attempt(db, signup_context)
    with (
        patch(
            "app.services.whatsapp_embedded_signup_service.exchange_whatsapp_embedded_signup_code"
        ) as exchange,
        pytest.raises(HTTPException) as denied,
    ):
        complete_whatsapp_embedded_signup(
            db,
            business_id=business.id,
            opaque_state=state,
            authorization_code="code",
            event_type="WA_EMBEDDED_SIGNUP",
            event_name="FINISH",
            meta_business_id=META_BUSINESS_ID,
            waba_id=WABA_ID,
            phone_number_id=PHONE_ID,
            actor=actor,
            session_token="different-session",
            settings=settings,
        )
    assert denied.value.status_code == 403
    assert not exchange.called
    db.refresh(attempt)
    assert attempt.status == "pending"

    failed = complete_whatsapp_embedded_signup(
        db,
        business_id=business.id,
        opaque_state=state,
        authorization_code="code",
        event_type="FAKE_EVENT",
        event_name="FINISH",
        meta_business_id=META_BUSINESS_ID,
        waba_id=WABA_ID,
        phone_number_id=PHONE_ID,
        actor=actor,
        session_token="signed-session-cookie",
        settings=settings,
    )
    assert failed.status == "failed"
    assert failed.safe_error_code == "sdk_event_invalid"


def test_registration_and_subscription_block_approval_but_retry_can_recover(db, signup_context):
    business, _other, _control, actor, owner = signup_context
    _attempt, state, _public, settings = start_attempt(db, signup_context)
    candidate = complete_candidate(db, state, actor, settings, registration="registration_required")
    assert candidate.phone_registration_status == "registration_required"
    with pytest.raises(HTTPException) as blocked:
        decide_whatsapp_signup_candidate(
            db,
            business_id=business.id,
            attempt_id=candidate.id,
            actor=owner,
            approve=True,
            reason="Aún no operativo",
        )
    assert blocked.value.status_code == 409
    assert db.query(BusinessChannelIntegration).count() == 0

    patches = success_patches(registration="registered")
    with patches[1], patches[2], patches[3]:
        retried = retry_whatsapp_candidate_setup(
            db, business_id=business.id, attempt_id=candidate.id, settings=settings
        )
    assert retried.app_subscription_status == "subscribed"
    assert retried.phone_registration_status == "registered"


def test_cross_business_assets_are_rejected_without_revealing_owner(db, signup_context):
    business, other, _control, actor, _owner = signup_context
    ciphertext, version = encrypt_secret("other-secret", settings=signup_settings())
    db.add(
        BusinessChannelIntegration(
            business_id=other.id,
            channel="whatsapp",
            provider="whatsapp",
            external_account_id=PHONE_ID,
            provider_account_id=WABA_ID,
            encrypted_access_token=ciphertext,
            encryption_key_version=version,
            integration_status="connected",
        )
    )
    db.commit()
    _attempt, state, _public, settings = start_attempt(db, signup_context)
    candidate = complete_candidate(db, state, actor, settings)
    assert candidate.status == "failed"
    assert candidate.safe_error_code == "asset_already_linked"
    assert other.name not in (candidate.safe_error_message or "")
    assert db.query(BusinessChannelIntegration).filter_by(business_id=business.id).count() == 0


def test_replacement_keeps_old_integration_until_approval_and_retires_routes(db, signup_context):
    business, _other, _control, actor, owner = signup_context
    settings = signup_settings()
    old_ciphertext, old_version = encrypt_secret("old-token", settings=settings)
    integration = BusinessChannelIntegration(
        business_id=business.id,
        channel="whatsapp",
        provider="whatsapp",
        external_account_id="600000000006",
        provider_account_id="700000000007",
        encrypted_access_token=old_ciphertext,
        encryption_key_version=old_version,
        integration_status="connected",
    )
    conversation = Conversation(
        business_id=business.id,
        channel="whatsapp",
        external_user_id="34611111111",
        external_conversation_id="old-route",
        status="open",
    )
    db.add_all([integration, conversation])
    db.commit()
    _attempt, state, _public, _settings = start_attempt(
        db, signup_context, settings=settings, purpose="replacement"
    )
    candidate = complete_candidate(db, state, actor, settings)
    db.refresh(integration)
    assert integration.external_account_id == "600000000006"
    assert (
        decrypt_secret(
            integration.encrypted_access_token,
            integration.encryption_key_version,
            settings=settings,
        )
        == "old-token"
    )
    db.refresh(conversation)
    assert conversation.status == "open"

    decide_whatsapp_signup_candidate(
        db,
        business_id=business.id,
        attempt_id=candidate.id,
        actor=owner,
        approve=True,
        reason="Reemplazo revisado",
    )
    db.commit()
    db.refresh(conversation)
    assert conversation.status == "closed"
    assert conversation.external_user_id.startswith("retired:")
    assert conversation.external_user_id.endswith("34611111111")
    assert conversation.external_conversation_id.startswith("retired:")


def test_provider_failure_consumes_attempt_and_never_stores_token(db, signup_context):
    business, _other, _control, actor, _owner = signup_context
    _attempt, state, _public, settings = start_attempt(db, signup_context)
    with patch(
        "app.services.whatsapp_embedded_signup_service.exchange_whatsapp_embedded_signup_code",
        side_effect=WhatsAppEmbeddedSignupProviderError(
            "token_exchange_rejected", "Meta rejected WhatsApp authorization"
        ),
    ):
        failed = complete_whatsapp_embedded_signup(
            db,
            business_id=business.id,
            opaque_state=state,
            authorization_code="rejected-code",
            event_type="WA_EMBEDDED_SIGNUP",
            event_name="FINISH",
            meta_business_id=META_BUSINESS_ID,
            waba_id=WABA_ID,
            phone_number_id=PHONE_ID,
            actor=actor,
            session_token="signed-session-cookie",
            settings=settings,
        )
    assert failed.status == "failed"
    assert failed.candidate_encrypted_access_token is None
    assert failed.candidate_waba_id is None


class FakeMetaResponse:
    def __init__(self, payload, *, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


def test_provider_validates_app_scopes_granular_waba_and_asset_ownership():
    settings = signup_settings()
    debug_payload = {
        "data": {
            "is_valid": True,
            "app_id": settings.meta_app_id,
            "type": "BUSINESS_INTEGRATION_SYSTEM_USER",
            "expires_at": 2_000_000_000,
            "scopes": list(WHATSAPP_EMBEDDED_SIGNUP_SCOPES),
            "granular_scopes": [
                {
                    "scope": "whatsapp_business_management",
                    "target_ids": [WABA_ID],
                }
            ],
        }
    }
    with patch(
        "app.services.whatsapp_embedded_signup_provider.requests.get",
        return_value=FakeMetaResponse(debug_payload),
    ):
        token = inspect_whatsapp_business_token(
            "business-token", expected_waba_id=WABA_ID, settings=settings
        )
    assert token.granted_scopes == WHATSAPP_EMBEDDED_SIGNUP_SCOPES

    missing_scope = {
        "data": {
            **debug_payload["data"],
            "scopes": ["business_management", "whatsapp_business_management"],
        }
    }
    with (
        patch(
            "app.services.whatsapp_embedded_signup_provider.requests.get",
            return_value=FakeMetaResponse(missing_scope),
        ),
        pytest.raises(WhatsAppEmbeddedSignupProviderError) as denied,
    ):
        inspect_whatsapp_business_token(
            "business-token", expected_waba_id=WABA_ID, settings=settings
        )
    assert denied.value.safe_code == "permissions_incomplete"

    responses = [
        FakeMetaResponse({"data": [{"id": WABA_ID}]}),
        FakeMetaResponse({"data": []}),
        FakeMetaResponse(
            {
                "data": [
                    {
                        "id": PHONE_ID,
                        "verified_name": "Verified Business",
                        "display_phone_number": "+34 600 000 000",
                        "quality_rating": "GREEN",
                        "code_verification_status": "VERIFIED",
                        "platform_type": "CLOUD_API",
                    }
                ]
            }
        ),
    ]
    with patch(
        "app.services.whatsapp_embedded_signup_provider.requests.get",
        side_effect=responses,
    ):
        assets = verify_whatsapp_embedded_signup_assets(
            "business-token",
            meta_business_id=META_BUSINESS_ID,
            waba_id=WABA_ID,
            phone_number_id=PHONE_ID,
            settings=settings,
        )
    assert assets.registration_status == "registered"
    assert assets.phone_number_id == PHONE_ID


def test_unknown_registration_state_is_never_treated_as_registered():
    responses = [
        FakeMetaResponse({"data": [{"id": WABA_ID}]}),
        FakeMetaResponse({"data": []}),
        FakeMetaResponse(
            {
                "data": [
                    {
                        "id": PHONE_ID,
                        "quality_rating": "GREEN",
                        "platform_type": "CLOUD_API",
                    }
                ]
            }
        ),
    ]
    with patch(
        "app.services.whatsapp_embedded_signup_provider.requests.get",
        side_effect=responses,
    ):
        assets = verify_whatsapp_embedded_signup_assets(
            "business-token",
            meta_business_id=META_BUSINESS_ID,
            waba_id=WABA_ID,
            phone_number_id=PHONE_ID,
            settings=signup_settings(),
        )
    assert assets.registration_status == "registration_required"


def test_migration_08_to_09_to_08_to_09(tmp_path):
    database = tmp_path / "whatsapp_signup_migration.db"
    database_url = f"sqlite:///{database.as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = database_url
    command.upgrade(config, "20260803_08")
    command.upgrade(config, "20260803_09")
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "whatsapp_embedded_signup_attempts" in inspector.get_table_names()
    assert "provider_account_id" in {
        item["name"] for item in inspector.get_columns("business_channel_integrations")
    }
    engine.dispose()
    command.downgrade(config, "20260803_08")
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "whatsapp_embedded_signup_attempts" not in inspector.get_table_names()
    assert "provider_account_id" not in {
        item["name"] for item in inspector.get_columns("business_channel_integrations")
    }
    engine.dispose()
    command.upgrade(config, "20260803_09")
    engine = create_engine(database_url)
    assert "whatsapp_embedded_signup_attempts" in inspect(engine).get_table_names()
    engine.dispose()
