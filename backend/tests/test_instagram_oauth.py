import base64
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.config import Settings
from app.core.database import Base
from app.core.migration_state import alembic_config
from app.models import (
    Business,
    BusinessChannelControl,
    BusinessChannelIntegration,
    BusinessUser,
    Conversation,
    InstagramOAuthAttempt,
    User,
)
from app.routers.instagram_oauth import instagram_oauth_callback
from app.services.instagram_login_provider import (
    INSTAGRAM_LOGIN_SCOPES,
    InstagramAccountProfile,
    InstagramLoginProviderError,
    InstagramTokenResult,
    build_instagram_authorization_url,
    exchange_instagram_authorization_code,
    exchange_instagram_long_lived_token,
    get_instagram_account_profile,
    subscribe_instagram_messages_webhook,
)
from app.services.instagram_oauth_service import (
    complete_instagram_oauth_callback,
    decide_instagram_oauth_candidate,
    retry_instagram_candidate_webhook,
    safe_instagram_return_path,
    serialize_instagram_oauth_attempt,
    start_instagram_oauth,
)
from app.services.integration_crypto_service import decrypt_secret, encrypt_secret


def oauth_settings() -> Settings:
    encryption_key = base64.urlsafe_b64encode(b"K" * 32).decode("ascii")
    return Settings(
        _env_file=None,
        app_env="test",
        session_secret="test-session-secret-with-at-least-32-characters",
        instagram_login_enabled=True,
        instagram_login_client_id="instagram-client-id",
        instagram_login_client_secret="instagram-client-secret",
        instagram_login_redirect_uri="https://app.autonogrow.test/api/integrations/instagram/callback",
        instagram_login_graph_api_version="v23.0",
        integration_encryption_keys_json=f'{{"v1":"{encryption_key}"}}',
        integration_encryption_active_key_version="v1",
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
def oauth_context(db):
    business = Business(slug="oauth-business", name="OAuth Business", status="active")
    other_business = Business(slug="other-business", name="Other Business", status="active")
    actor = User(email="admin@oauth.test", is_active=True)
    owner = User(email="owner@oauth.test", is_owner=True, is_active=True)
    db.add_all([business, other_business, actor, owner])
    db.flush()
    control = BusinessChannelControl(
        business_id=business.id,
        channel="instagram",
        status="available",
        connector_policy="business_admin",
        connection_mode="oauth",
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
    return business, other_business, control, actor, owner


def opaque_state(authorization_url: str) -> str:
    return parse_qs(urlsplit(authorization_url).query)["state"][0]


def provider_success_patches(*, account_id="17841410000000001", account_name="autonogrow"):
    return (
        patch(
            "app.services.instagram_oauth_service.exchange_instagram_authorization_code",
            return_value=InstagramTokenResult(
                "short-secret-token", None, "bearer", INSTAGRAM_LOGIN_SCOPES
            ),
        ),
        patch(
            "app.services.instagram_oauth_service.exchange_instagram_long_lived_token",
            return_value=InstagramTokenResult(
                "long-secret-token",
                datetime.now(timezone.utc) + timedelta(days=60),
                "bearer",
                INSTAGRAM_LOGIN_SCOPES,
            ),
        ),
        patch(
            "app.services.instagram_oauth_service.get_instagram_account_profile",
            return_value=InstagramAccountProfile(
                external_account_id=account_id,
                scoped_account_id="scoped-professional-id",
                account_name=account_name,
                account_type="BUSINESS",
            ),
        ),
        patch("app.services.instagram_oauth_service.subscribe_instagram_messages_webhook"),
    )


def start_candidate(db, oauth_context, *, settings=None, purpose=None):
    business, _other, control, actor, _owner = oauth_context
    settings = settings or oauth_settings()
    attempt, authorization_url = start_instagram_oauth(
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
    return attempt, opaque_state(authorization_url), settings


def complete_candidate(db, state, actor, settings, *, account_id="17841410000000001"):
    patches = provider_success_patches(account_id=account_id)
    with patches[0], patches[1], patches[2], patches[3]:
        return complete_instagram_oauth_callback(
            db,
            opaque_state=state,
            authorization_code="single-use-code",
            provider_denied=False,
            actor=actor,
            session_token="signed-session-cookie",
            settings=settings,
        )


def test_start_persists_only_hashed_state_and_fixed_internal_return_path(db, oauth_context):
    attempt, state, settings = start_candidate(db, oauth_context)

    assert len(state) >= 32
    assert attempt.state_hash == hashlib.sha256(state.encode()).hexdigest()
    assert state not in attempt.state_hash
    assert attempt.return_path == "/autonogrow-admin/index.html?b=oauth-business"
    assert attempt.status == "pending"
    assert attempt.candidate_encrypted_access_token is None
    url = build_instagram_authorization_url(state, settings=settings)
    query = parse_qs(urlsplit(url).query)
    assert query["scope"] == [",".join(INSTAGRAM_LOGIN_SCOPES)]
    assert query["redirect_uri"] == [settings.instagram_login_redirect_uri]
    assert safe_instagram_return_path("https://evil.test/") == "/autonogrow-admin/index.html"


def test_callback_creates_encrypted_candidate_and_replay_is_rejected(db, oauth_context):
    business, _other, control, actor, owner = oauth_context
    _attempt, state, settings = start_candidate(db, oauth_context)
    candidate = complete_candidate(db, state, actor, settings)

    assert candidate.status == "candidate_ready"
    assert candidate.consumed_at is not None
    assert candidate.candidate_encrypted_access_token != "long-secret-token"
    assert decrypt_secret(
        candidate.candidate_encrypted_access_token,
        candidate.candidate_encryption_key_version,
        settings=settings,
    ) == "long-secret-token"
    assert control.status == "pending_approval"
    assert control.connection_mode == "oauth"
    assert not control.integrated_delivery_enabled
    assert not control.automation_enabled
    assert db.query(BusinessChannelIntegration).count() == 0

    with pytest.raises(HTTPException) as replay:
        complete_instagram_oauth_callback(
            db,
            opaque_state=state,
            authorization_code="replayed-code",
            provider_denied=False,
            actor=actor,
            session_token="signed-session-cookie",
            settings=settings,
        )
    assert replay.value.status_code == 409

    decided, integration = decide_instagram_oauth_candidate(
        db,
        business_id=business.id,
        attempt_id=candidate.id,
        actor=owner,
        approve=True,
        reason="Cuenta profesional revisada",
    )
    db.commit()
    assert decided.status == "approved"
    assert decided.candidate_encrypted_access_token is None
    assert integration.integration_status == "connected"
    assert decrypt_secret(
        integration.encrypted_access_token,
        integration.encryption_key_version,
        settings=settings,
    ) == "long-secret-token"
    assert control.status == "approved"
    assert not control.integrated_delivery_enabled
    assert not control.automation_enabled


def test_session_mismatch_does_not_consume_state_or_call_meta(db, oauth_context):
    _business, _other, _control, actor, _owner = oauth_context
    attempt, state, settings = start_candidate(db, oauth_context)
    with (
        patch("app.services.instagram_oauth_service.exchange_instagram_authorization_code") as exchange,
        pytest.raises(HTTPException) as denied,
    ):
        complete_instagram_oauth_callback(
            db,
            opaque_state=state,
            authorization_code="code",
            provider_denied=False,
            actor=actor,
            session_token="another-session-cookie",
            settings=settings,
        )
    assert denied.value.status_code == 403
    db.refresh(attempt)
    assert attempt.status == "pending"
    exchange.assert_not_called()


def test_provider_failure_is_safe_and_state_stays_non_reusable(db, oauth_context):
    _business, _other, _control, actor, _owner = oauth_context
    attempt, state, settings = start_candidate(db, oauth_context)
    with patch(
        "app.services.instagram_oauth_service.exchange_instagram_authorization_code",
        side_effect=InstagramLoginProviderError("token_exchange_rejected", "Safe failure"),
    ):
        failed = complete_instagram_oauth_callback(
            db,
            opaque_state=state,
            authorization_code="provider-code",
            provider_denied=False,
            actor=actor,
            session_token="signed-session-cookie",
            settings=settings,
        )
    assert failed.status == "failed"
    assert failed.safe_error_code == "token_exchange_rejected"
    assert failed.candidate_encrypted_access_token is None
    assert failed.consumed_at is not None
    assert "provider-code" not in str(failed.__dict__)
    assert state not in str(failed.__dict__)
    assert attempt.id == failed.id


def test_webhook_failure_keeps_reviewable_candidate_and_owner_can_retry(db, oauth_context):
    business, _other, _control, actor, _owner = oauth_context
    _attempt, state, settings = start_candidate(db, oauth_context)
    patches = list(provider_success_patches())
    patches[3] = patch(
        "app.services.instagram_oauth_service.subscribe_instagram_messages_webhook",
        side_effect=InstagramLoginProviderError(
            "webhook_subscription_timeout", "Instagram did not respond"
        ),
    )
    with patches[0], patches[1], patches[2], patches[3]:
        candidate = complete_instagram_oauth_callback(
            db,
            opaque_state=state,
            authorization_code="single-use-code",
            provider_denied=False,
            actor=actor,
            session_token="signed-session-cookie",
            settings=settings,
        )
    assert candidate.status == "candidate_ready"
    assert candidate.webhook_subscription_status == "failed"
    assert candidate.candidate_encrypted_access_token

    with patch("app.services.instagram_oauth_service.subscribe_instagram_messages_webhook"):
        retried = retry_instagram_candidate_webhook(
            db,
            business_id=business.id,
            attempt_id=candidate.id,
            settings=settings,
        )
    db.commit()
    assert retried.webhook_subscription_status == "subscribed"
    assert retried.safe_error_code is None


def test_account_linked_to_another_business_never_persists_candidate_token(db, oauth_context):
    _business, other, _control, actor, _owner = oauth_context
    account_id = "17841410000000009"
    encrypted, version = encrypt_secret("other-token", settings=oauth_settings())
    db.add(
        BusinessChannelIntegration(
            business_id=other.id,
            channel="instagram",
            provider="instagram",
            external_account_id=account_id,
            encrypted_access_token=encrypted,
            encryption_key_version=version,
            integration_status="connected",
        )
    )
    db.commit()
    attempt, state, settings = start_candidate(db, oauth_context)
    failed = complete_candidate(db, state, actor, settings, account_id=account_id)
    assert failed.status == "failed"
    assert failed.safe_error_code == "account_already_linked"
    assert failed.candidate_encrypted_access_token is None
    assert db.query(BusinessChannelIntegration).count() == 1
    db.refresh(attempt)
    assert attempt.candidate_external_account_id is None


def test_replacement_preserves_capabilities_and_retires_old_conversation_routes(db, oauth_context):
    business, _other, control, actor, owner = oauth_context
    settings = oauth_settings()
    old_ciphertext, old_version = encrypt_secret("old-token", settings=settings)
    integration = BusinessChannelIntegration(
        business_id=business.id,
        channel="instagram",
        provider="instagram",
        external_account_id="old-account",
        encrypted_access_token=old_ciphertext,
        encryption_key_version=old_version,
        integration_status="connected",
    )
    conversation = Conversation(
        business_id=business.id,
        channel="instagram",
        external_user_id="shared-sender-id",
        external_conversation_id="shared-sender-id",
        status="pending",
    )
    db.add_all([integration, conversation])
    control.status = "approved"
    control.integrated_delivery_enabled = True
    control.automation_enabled = True
    db.commit()

    _attempt, state, settings = start_candidate(
        db, oauth_context, settings=settings, purpose="replacement"
    )
    candidate = complete_candidate(
        db, state, actor, settings, account_id="new-account"
    )
    assert integration.external_account_id == "old-account"
    assert control.integrated_delivery_enabled
    assert control.automation_enabled

    _decided, promoted = decide_instagram_oauth_candidate(
        db,
        business_id=business.id,
        attempt_id=candidate.id,
        actor=owner,
        approve=True,
        reason="Reemplazo de cuenta revisado",
    )
    db.commit()
    assert promoted.id == integration.id
    assert promoted.external_account_id == "new-account"
    assert decrypt_secret(
        promoted.encrypted_access_token,
        promoted.encryption_key_version,
        settings=settings,
    ) == "long-secret-token"
    assert conversation.external_user_id is None
    assert conversation.external_conversation_id.startswith("retired:old-account:")
    assert conversation.status == "closed"
    assert control.integrated_delivery_enabled
    assert control.automation_enabled


def test_regranted_channel_can_reconnect_and_requires_fresh_owner_approval(db, oauth_context):
    business, _other, control, actor, owner = oauth_context
    settings = oauth_settings()
    old_ciphertext, old_version = encrypt_secret("old-token", settings=settings)
    integration = BusinessChannelIntegration(
        business_id=business.id,
        channel="instagram",
        provider="instagram",
        external_account_id="same-account",
        encrypted_access_token=old_ciphertext,
        encryption_key_version=old_version,
        integration_status="revoked",
    )
    db.add(integration)
    control.status = "available"
    control.integrated_delivery_enabled = False
    control.automation_enabled = False
    db.commit()

    _attempt, state, settings = start_candidate(db, oauth_context, settings=settings)
    candidate = complete_candidate(
        db,
        state,
        actor,
        settings,
        account_id="same-account",
    )
    assert candidate.purpose == "reconnect"
    assert control.status == "pending_approval"
    assert integration.integration_status == "revoked"

    _decided, promoted = decide_instagram_oauth_candidate(
        db,
        business_id=business.id,
        attempt_id=candidate.id,
        actor=owner,
        approve=True,
        reason="Reconexion revisada tras nueva concesion",
    )
    db.commit()
    assert promoted.id == integration.id
    assert promoted.integration_status == "connected"
    assert control.status == "approved"
    assert not control.integrated_delivery_enabled
    assert not control.automation_enabled


def test_rejection_clears_candidate_and_restores_initial_control(db, oauth_context):
    business, _other, control, actor, owner = oauth_context
    _attempt, state, settings = start_candidate(db, oauth_context)
    candidate = complete_candidate(db, state, actor, settings)
    rejected, integration = decide_instagram_oauth_candidate(
        db,
        business_id=business.id,
        attempt_id=candidate.id,
        actor=owner,
        approve=False,
        reason="Identidad no corresponde al negocio",
    )
    db.commit()
    assert integration is None
    assert rejected.status == "rejected"
    assert rejected.candidate_encrypted_access_token is None
    assert control.status == "available"
    assert not control.integrated_delivery_enabled
    assert not control.automation_enabled


def test_safe_candidate_response_exposes_no_state_or_credentials(db, oauth_context):
    _business, _other, _control, actor, _owner = oauth_context
    _attempt, state, settings = start_candidate(db, oauth_context)
    candidate = complete_candidate(db, state, actor, settings)
    payload = serialize_instagram_oauth_attempt(candidate)
    rendered = str(payload)
    assert "state_hash" not in payload
    assert "session_fingerprint_hash" not in payload
    assert "encrypted" not in rendered
    assert "long-secret-token" not in rendered


def test_callback_without_session_is_rejected_before_state_processing(db):
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/integrations/instagram/callback",
            "headers": [],
        }
    )
    with pytest.raises(HTTPException) as denied:
        instagram_oauth_callback(
            request,
            state="x" * 48,
            code="code",
            error=None,
            error_reason=None,
            error_description=None,
            actor=None,
            db=db,
        )
    assert denied.value.status_code == 401
    assert db.query(InstagramOAuthAttempt).count() == 0


def test_provider_contract_uses_only_minimum_scopes_and_configured_version():
    settings = oauth_settings()
    response = SimpleNamespace(
        ok=True,
        json=lambda: {
            "access_token": "short-token",
            "permissions": list(INSTAGRAM_LOGIN_SCOPES) + ["unexpected_permission"],
        },
    )
    with patch("app.services.instagram_login_provider.requests.post", return_value=response) as post:
        result = exchange_instagram_authorization_code("one-time-code", settings=settings)
    assert result.access_token == "short-token"
    assert result.granted_scopes == INSTAGRAM_LOGIN_SCOPES
    assert post.call_args.args[0] == "https://api.instagram.com/oauth/access_token"
    assert post.call_args.kwargs["data"]["code"] == "one-time-code"

    long_response = SimpleNamespace(
        ok=True,
        json=lambda: {"access_token": "long-token", "expires_in": 3600, "token_type": "bearer"},
    )
    with patch("app.services.instagram_login_provider.requests.get", return_value=long_response) as get:
        long_result = exchange_instagram_long_lived_token("short-token", settings=settings)
    assert long_result.access_token == "long-token"
    assert get.call_args.args[0] == "https://graph.instagram.com/access_token"

    profile_response = SimpleNamespace(
        ok=True,
        json=lambda: {
            "id": "scoped-id",
            "user_id": "routing-id",
            "username": "business",
            "account_type": "CREATOR",
        },
    )
    with patch("app.services.instagram_login_provider.requests.get", return_value=profile_response) as get:
        profile = get_instagram_account_profile("long-token", settings=settings)
    assert profile.external_account_id == "routing-id"
    assert get.call_args.args[0] == "https://graph.instagram.com/v23.0/me"

    subscribed = SimpleNamespace(ok=True, json=lambda: {"success": True})
    with patch("app.services.instagram_login_provider.requests.post", return_value=subscribed) as post:
        subscribe_instagram_messages_webhook("routing-id", "long-token", settings=settings)
    assert post.call_args.kwargs["params"] == {"subscribed_fields": "messages"}


def test_partial_permissions_and_non_professional_account_are_rejected():
    settings = oauth_settings()
    partial = SimpleNamespace(
        ok=True,
        json=lambda: {
            "access_token": "short-token",
            "permissions": ["instagram_business_basic"],
        },
    )
    with (
        patch("app.services.instagram_login_provider.requests.post", return_value=partial),
        pytest.raises(InstagramLoginProviderError) as denied,
    ):
        exchange_instagram_authorization_code("code", settings=settings)
    assert denied.value.safe_code == "permissions_incomplete"

    personal = SimpleNamespace(
        ok=True,
        json=lambda: {
            "id": "scoped-id",
            "user_id": "routing-id",
            "username": "personal",
            "account_type": "PERSONAL",
        },
    )
    with (
        patch("app.services.instagram_login_provider.requests.get", return_value=personal),
        pytest.raises(InstagramLoginProviderError) as denied,
    ):
        get_instagram_account_profile("token", settings=settings)
    assert denied.value.safe_code == "professional_account_required"


def test_start_rejects_staff_suspended_and_disabled_login(db, oauth_context):
    business, _other, control, actor, _owner = oauth_context
    with pytest.raises(HTTPException) as staff:
        start_instagram_oauth(
            db,
            business=business,
            control=control,
            actor=actor,
            actor_role="business_staff",
            session_token="session",
            settings=oauth_settings(),
        )
    assert staff.value.status_code == 403

    control.status = "suspended"
    with pytest.raises(HTTPException) as suspended:
        start_instagram_oauth(
            db,
            business=business,
            control=control,
            actor=actor,
            actor_role="business_admin",
            session_token="session",
            settings=oauth_settings(),
        )
    assert suspended.value.status_code == 409

    disabled = oauth_settings().model_copy(update={"instagram_login_enabled": False})
    with pytest.raises(HTTPException) as unavailable:
        start_instagram_oauth(
            db,
            business=business,
            control=control,
            actor=actor,
            actor_role="business_admin",
            session_token="session",
            settings=disabled,
        )
    assert unavailable.value.status_code == 503


def production_login_settings(**overrides) -> dict:
    encryption_key = base64.urlsafe_b64encode(b"P" * 32).decode("ascii")
    values = {
        "app_env": "production",
        "cookie_secure": True,
        "csrf_enabled": True,
        "rate_limit_enabled": True,
        "security_headers_enabled": True,
        "frontend_origins": "https://app.autonogrow.test",
        "session_secret": "production-session-secret-with-at-least-32-characters",
        "google_client_id": "1234567890-real.apps.googleusercontent.com",
        "owner_allowed_emails": "owner@autonogrow.test",
        "database_url": "postgresql+psycopg://user:test-only@localhost/autonogrow",
        "uploads_dir": "C:/var/lib/autonogrow/uploads",
        "instagram_provider_enabled": True,
        "instagram_require_signature": True,
        "meta_app_id": "meta-app-id",
        "meta_app_secret": "meta-app-secret",
        "meta_verify_token": "meta-verify-token",
        "integration_encryption_keys_json": f'{{"v1":"{encryption_key}"}}',
        "integration_encryption_active_key_version": "v1",
        "instagram_login_enabled": True,
        "instagram_login_client_id": "instagram-client-id",
        "instagram_login_client_secret": "instagram-client-secret",
        "instagram_login_redirect_uri": (
            "https://app.autonogrow.test/api/integrations/instagram/callback"
        ),
    }
    return {**values, **overrides}


def test_login_configuration_is_optional_but_strict_when_enabled():
    disabled = Settings(_env_file=None, instagram_login_enabled=False)
    assert not disabled.instagram_login_enabled
    with pytest.raises(ValueError):
        Settings(_env_file=None, instagram_login_graph_api_version="latest")
    Settings(_env_file=None, **production_login_settings())
    for override in (
        {"instagram_login_client_secret": ""},
        {"instagram_login_redirect_uri": "http://app.autonogrow.test/api/integrations/instagram/callback"},
        {"instagram_login_redirect_uri": "https://evil.test/api/integrations/instagram/callback"},
        {"instagram_login_redirect_uri": "https://app.autonogrow.test/api/integrations/instagram/callback?next=evil"},
        {"instagram_provider_enabled": False},
    ):
        with pytest.raises(ValueError):
            Settings(_env_file=None, **production_login_settings(**override))


def test_migration_08_upgrade_downgrade_and_reupgrade(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'oauth-migration.db').as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = database_url
    command.upgrade(config, "20260802_07")
    engine = create_engine(database_url)
    assert "instagram_oauth_attempts" not in inspect(engine).get_table_names()
    engine.dispose()

    command.upgrade(config, "20260803_08")
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "instagram_oauth_attempts" in inspector.get_table_names()
    indexes = {item["name"] for item in inspector.get_indexes("instagram_oauth_attempts")}
    assert {
        "ix_instagram_oauth_attempts_business_id",
        "ix_instagram_oauth_attempts_user_id",
        "ix_instagram_oauth_attempts_status",
        "ix_instagram_oauth_attempts_expires_at",
    } <= indexes
    engine.dispose()

    command.downgrade(config, "20260802_07")
    engine = create_engine(database_url)
    assert "instagram_oauth_attempts" not in inspect(engine).get_table_names()
    engine.dispose()
    command.upgrade(config, "20260803_08")
    engine = create_engine(database_url)
    assert "instagram_oauth_attempts" in inspect(engine).get_table_names()
    engine.dispose()
