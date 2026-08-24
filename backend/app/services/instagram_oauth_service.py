from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    Business,
    BusinessChannelControl,
    BusinessChannelIntegration,
    BusinessUser,
    Conversation,
    InstagramMediaSyncState,
    InstagramOAuthAttempt,
    InstagramRemoteMedia,
    User,
)
from app.services.channel_control_service import utc_now
from app.services.instagram_integration_service import (
    INSTAGRAM_CHANNEL,
    INSTAGRAM_PROVIDER,
    get_instagram_integration,
    mask_external_account_id,
)
from app.services.instagram_login_provider import (
    InstagramLoginProviderError,
    build_instagram_authorization_url,
    exchange_instagram_authorization_code,
    exchange_instagram_long_lived_token,
    get_instagram_account_profile,
    subscribe_instagram_messages_webhook,
)
from app.services.integration_crypto_service import (
    IntegrationCryptoError,
    decrypt_secret,
    encrypt_secret,
)

CANDIDATE_STATUSES = ("candidate_ready",)
ACTIVE_STATE_STATUSES = ("pending", "processing")


def _as_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def session_fingerprint(session_token: str, *, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return hmac.new(
        settings.session_secret.encode("utf-8"),
        session_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def safe_instagram_return_path(value: str) -> str:
    if value == "/autonogrow-owner/index.html":
        return value
    if re.fullmatch(
        r"/autonogrow-admin/index\.html\?b=[a-z0-9]+(?:-[a-z0-9]+)*",
        value,
    ):
        return value
    return "/autonogrow-admin/index.html"


def _ensure_login_configured(settings: Settings) -> None:
    if not settings.instagram_login_enabled:
        raise HTTPException(status_code=503, detail="Instagram Login is not enabled")
    if not all(
        value.strip()
        for value in (
            settings.instagram_login_client_id,
            settings.instagram_login_client_secret,
            settings.instagram_login_redirect_uri,
            settings.session_secret,
        )
    ):
        raise HTTPException(status_code=503, detail="Instagram Login is not configured")


def _actor_can_connect(control: BusinessChannelControl, actor: User, actor_role: str) -> bool:
    return actor.is_owner or (
        actor_role == "business_admin" and control.connector_policy == "business_admin"
    )


def _purpose_for_business(
    db: Session,
    *,
    business_id: int,
    requested_purpose: str | None,
) -> str:
    integration = get_instagram_integration(db, business_id=business_id)
    if integration is None:
        if requested_purpose not in {None, "initial_connection"}:
            raise HTTPException(status_code=409, detail="Instagram is not connected yet")
        return "initial_connection"
    purpose = requested_purpose or "reconnect"
    if purpose == "initial_connection":
        raise HTTPException(status_code=409, detail="Instagram is already connected")
    if purpose not in {"reconnect", "replacement"}:
        raise HTTPException(status_code=422, detail="Invalid Instagram connection purpose")
    return purpose


def start_instagram_oauth(
    db: Session,
    *,
    business: Business,
    control: BusinessChannelControl,
    actor: User,
    actor_role: str,
    session_token: str,
    requested_purpose: str | None = None,
    owner_return: bool = False,
    settings: Settings | None = None,
) -> tuple[InstagramOAuthAttempt, str]:
    settings = settings or get_settings()
    _ensure_login_configured(settings)
    expire_instagram_oauth_attempts(db, business_id=business.id)
    if control.channel != INSTAGRAM_CHANNEL:
        raise HTTPException(status_code=404, detail="Instagram channel control not found")
    if not _actor_can_connect(control, actor, actor_role):
        raise HTTPException(status_code=403, detail="You cannot connect assets for this channel")
    purpose = _purpose_for_business(
        db, business_id=business.id, requested_purpose=requested_purpose
    )
    if purpose == "initial_connection" and control.status != "available":
        raise HTTPException(status_code=409, detail="Instagram is not available for connection")
    if purpose != "initial_connection" and control.status not in {"available", "approved"}:
        raise HTTPException(status_code=409, detail="Instagram channel is not reconnectable")

    ready = (
        db.query(InstagramOAuthAttempt.id)
        .filter(
            InstagramOAuthAttempt.business_id == business.id,
            InstagramOAuthAttempt.status == "candidate_ready",
        )
        .first()
    )
    if ready is not None:
        raise HTTPException(
            status_code=409, detail="An Instagram candidate is awaiting Owner review"
        )
    processing = (
        db.query(InstagramOAuthAttempt.id)
        .filter(
            InstagramOAuthAttempt.business_id == business.id,
            InstagramOAuthAttempt.user_id == actor.id,
            InstagramOAuthAttempt.purpose == purpose,
            InstagramOAuthAttempt.status == "processing",
        )
        .first()
    )
    if processing is not None:
        raise HTTPException(status_code=409, detail="An Instagram authorization is being processed")

    now = utc_now()
    db.query(InstagramOAuthAttempt).filter(
        InstagramOAuthAttempt.business_id == business.id,
        InstagramOAuthAttempt.user_id == actor.id,
        InstagramOAuthAttempt.purpose == purpose,
        InstagramOAuthAttempt.status == "pending",
    ).update(
        {
            InstagramOAuthAttempt.status: "cancelled",
            InstagramOAuthAttempt.invalidated_at: now,
            InstagramOAuthAttempt.safe_error_code: "superseded",
            InstagramOAuthAttempt.safe_error_message: "A newer authorization was started",
        },
        synchronize_session=False,
    )

    opaque_state = token_urlsafe(48)
    return_path = (
        "/autonogrow-owner/index.html"
        if owner_return
        else f"/autonogrow-admin/index.html?b={business.slug}"
    )
    attempt = InstagramOAuthAttempt(
        business_id=business.id,
        user_id=actor.id,
        channel_control_id=control.id,
        purpose=purpose,
        status="pending",
        state_hash=_hash_value(opaque_state),
        session_fingerprint_hash=session_fingerprint(session_token, settings=settings),
        return_path=return_path,
        created_at=now,
        expires_at=now + timedelta(seconds=settings.instagram_oauth_attempt_ttl_seconds),
        metadata_json=json.dumps({"scope_source": "requested_minimum"}, sort_keys=True),
    )
    db.add(attempt)
    db.flush()
    return attempt, build_instagram_authorization_url(opaque_state, settings=settings)


def _clear_candidate_credentials(attempt: InstagramOAuthAttempt) -> None:
    attempt.candidate_external_account_id = None
    attempt.candidate_external_account_name = None
    attempt.candidate_account_type = None
    attempt.candidate_encrypted_access_token = None
    attempt.candidate_encryption_key_version = None
    attempt.candidate_token_expires_at = None
    attempt.candidate_granted_scopes = None
    attempt.webhook_subscription_status = None
    attempt.metadata_json = None


def _fail_processing_attempt(
    db: Session,
    *,
    attempt_id: int,
    safe_code: str,
    safe_message: str,
) -> InstagramOAuthAttempt:
    attempt = db.get(InstagramOAuthAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=400, detail="Invalid Instagram authorization")
    attempt.status = "failed"
    attempt.safe_error_code = safe_code[:80]
    attempt.safe_error_message = safe_message[:500]
    attempt.webhook_subscription_status = (
        "failed"
        if safe_code.startswith("webhook_subscription")
        else attempt.webhook_subscription_status
    )
    _clear_candidate_credentials(attempt)
    db.commit()
    return attempt


def consume_instagram_oauth_state(
    db: Session,
    *,
    opaque_state: str,
    actor: User,
    session_token: str,
    settings: Settings | None = None,
) -> InstagramOAuthAttempt:
    settings = settings or get_settings()
    if not 32 <= len(opaque_state) <= 512:
        raise HTTPException(status_code=400, detail="Invalid Instagram authorization")
    state_hash = _hash_value(opaque_state)
    attempt = (
        db.query(InstagramOAuthAttempt)
        .filter(InstagramOAuthAttempt.state_hash == state_hash)
        .first()
    )
    if attempt is None or attempt.status != "pending":
        raise HTTPException(status_code=409, detail="Instagram authorization was already used")
    now = utc_now()
    if _as_utc(attempt.expires_at) <= now:
        attempt.status = "expired"
        attempt.invalidated_at = now
        attempt.safe_error_code = "state_expired"
        attempt.safe_error_message = "Instagram authorization expired"
        db.commit()
        raise HTTPException(status_code=410, detail="Instagram authorization expired")
    expected_fingerprint = session_fingerprint(session_token, settings=settings)
    if attempt.user_id != actor.id or not hmac.compare_digest(
        attempt.session_fingerprint_hash, expected_fingerprint
    ):
        raise HTTPException(status_code=403, detail="Instagram authorization session mismatch")
    control = db.get(BusinessChannelControl, attempt.channel_control_id)
    if (
        control is None
        or control.business_id != attempt.business_id
        or control.channel != INSTAGRAM_CHANNEL
    ):
        raise HTTPException(status_code=400, detail="Invalid Instagram authorization")
    if not actor.is_owner:
        membership = (
            db.query(BusinessUser.id)
            .filter(
                BusinessUser.business_id == attempt.business_id,
                BusinessUser.user_id == actor.id,
                BusinessUser.role == "business_admin",
                BusinessUser.active.is_(True),
            )
            .first()
        )
        if membership is None:
            raise HTTPException(status_code=403, detail="Business administrator access required")

    # Compare-and-swap is the concurrency boundary. PostgreSQL row locking is
    # not required for correctness and SQLite tests get the same one-time rule.
    updated = (
        db.query(InstagramOAuthAttempt)
        .filter(
            InstagramOAuthAttempt.id == attempt.id,
            InstagramOAuthAttempt.status == "pending",
        )
        .update(
            {
                InstagramOAuthAttempt.status: "processing",
                InstagramOAuthAttempt.consumed_at: now,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Instagram authorization was already used")
    db.commit()
    consumed = db.get(InstagramOAuthAttempt, attempt.id)
    if consumed is None:
        raise HTTPException(status_code=409, detail="Instagram authorization is unavailable")
    return consumed


def complete_instagram_oauth_callback(
    db: Session,
    *,
    opaque_state: str,
    authorization_code: str | None,
    provider_denied: bool,
    actor: User,
    session_token: str,
    settings: Settings | None = None,
) -> InstagramOAuthAttempt:
    settings = settings or get_settings()
    _ensure_login_configured(settings)
    attempt = consume_instagram_oauth_state(
        db,
        opaque_state=opaque_state,
        actor=actor,
        session_token=session_token,
        settings=settings,
    )
    if provider_denied:
        return _fail_processing_attempt(
            db,
            attempt_id=attempt.id,
            safe_code="authorization_denied",
            safe_message="Instagram authorization was cancelled",
        )
    if not authorization_code or not 4 <= len(authorization_code) <= 2048:
        return _fail_processing_attempt(
            db,
            attempt_id=attempt.id,
            safe_code="authorization_code_missing",
            safe_message="Instagram authorization code was not received",
        )

    try:
        short_token = exchange_instagram_authorization_code(authorization_code, settings=settings)
        long_token = exchange_instagram_long_lived_token(
            short_token.access_token,
            granted_scopes=short_token.granted_scopes,
            settings=settings,
        )
        profile = get_instagram_account_profile(long_token.access_token, settings=settings)
        existing_owner = (
            db.query(BusinessChannelIntegration)
            .filter(
                BusinessChannelIntegration.provider == INSTAGRAM_PROVIDER,
                BusinessChannelIntegration.external_account_id == profile.external_account_id,
                BusinessChannelIntegration.business_id != attempt.business_id,
            )
            .first()
        )
        pending_owner = (
            db.query(InstagramOAuthAttempt)
            .filter(
                InstagramOAuthAttempt.status == "candidate_ready",
                InstagramOAuthAttempt.candidate_external_account_id == profile.external_account_id,
                InstagramOAuthAttempt.business_id != attempt.business_id,
            )
            .first()
        )
        if existing_owner is not None or pending_owner is not None:
            return _fail_processing_attempt(
                db,
                attempt_id=attempt.id,
                safe_code="account_already_linked",
                safe_message="Instagram account is already linked to another business",
            )
        db.commit()
    except InstagramLoginProviderError as exc:
        return _fail_processing_attempt(
            db,
            attempt_id=attempt.id,
            safe_code=exc.safe_code,
            safe_message=exc.safe_message,
        )

    webhook_error: InstagramLoginProviderError | None = None
    try:
        subscribe_instagram_messages_webhook(
            profile.external_account_id,
            long_token.access_token,
            settings=settings,
        )
    except InstagramLoginProviderError as exc:
        webhook_error = exc
    try:
        ciphertext, key_version = encrypt_secret(long_token.access_token, settings=settings)
    except IntegrationCryptoError:
        return _fail_processing_attempt(
            db,
            attempt_id=attempt.id,
            safe_code="credential_encryption_failed",
            safe_message="Instagram credentials could not be protected",
        )

    refreshed_attempt = db.get(InstagramOAuthAttempt, attempt.id)
    if refreshed_attempt is None or refreshed_attempt.status != "processing":
        raise HTTPException(status_code=409, detail="Instagram authorization is no longer active")
    attempt = refreshed_attempt
    control = db.get(BusinessChannelControl, attempt.channel_control_id)
    if control is None:
        raise HTTPException(status_code=409, detail="Instagram authorization is no longer active")
    active_integration = get_instagram_integration(db, business_id=attempt.business_id)
    actual_purpose = (
        "initial_connection"
        if active_integration is None
        else (
            "reconnect"
            if active_integration.external_account_id == profile.external_account_id
            else "replacement"
        )
    )
    attempt.purpose = actual_purpose
    attempt.status = "candidate_ready"
    review_expires_at = utc_now() + timedelta(hours=settings.instagram_candidate_review_ttl_hours)
    if long_token.expires_at is not None:
        review_expires_at = min(review_expires_at, _as_utc(long_token.expires_at))
    attempt.expires_at = review_expires_at
    attempt.candidate_external_account_id = profile.external_account_id
    attempt.candidate_external_account_name = profile.account_name
    attempt.candidate_account_type = profile.account_type
    attempt.candidate_encrypted_access_token = ciphertext
    attempt.candidate_encryption_key_version = key_version
    attempt.candidate_token_expires_at = long_token.expires_at
    attempt.candidate_granted_scopes = json.dumps(list(long_token.granted_scopes))
    attempt.webhook_subscription_status = "failed" if webhook_error else "subscribed"
    attempt.safe_error_code = webhook_error.safe_code if webhook_error else None
    attempt.safe_error_message = webhook_error.safe_message if webhook_error else None
    attempt.metadata_json = json.dumps(
        {
            "provider_scoped_account_id": profile.scoped_account_id,
            "scope_source": "requested_minimum",
        },
        sort_keys=True,
    )
    if control.status == "available":
        control.status = "pending_approval"
        control.connection_mode = "oauth"
        control.requested_by_user_id = actor.id
        control.requested_at = utc_now()
        control.approved_by_user_id = None
        control.approved_at = None
        control.integrated_delivery_enabled = False
        control.automation_enabled = False
        control.updated_by_user_id = actor.id
        control.last_reason = "Instagram OAuth candidate awaiting Owner approval"
    attempt_id = attempt.id
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return _fail_processing_attempt(
            db,
            attempt_id=attempt_id,
            safe_code="account_already_linked",
            safe_message="Instagram account is already linked",
        )
    db.refresh(attempt)
    return attempt


def serialize_instagram_oauth_attempt(attempt: InstagramOAuthAttempt) -> dict:
    return {
        "id": attempt.id,
        "business_id": attempt.business_id,
        "purpose": attempt.purpose,
        "status": attempt.status,
        "candidate_external_account_id_masked": mask_external_account_id(
            attempt.candidate_external_account_id or ""
        )
        or None,
        "candidate_external_account_name": attempt.candidate_external_account_name,
        "candidate_account_type": attempt.candidate_account_type,
        "candidate_token_expires_at": attempt.candidate_token_expires_at,
        "candidate_granted_scopes": (
            json.loads(attempt.candidate_granted_scopes) if attempt.candidate_granted_scopes else []
        ),
        "webhook_subscription_status": attempt.webhook_subscription_status,
        "safe_error_code": attempt.safe_error_code,
        "safe_error_message": attempt.safe_error_message,
        "created_at": attempt.created_at,
        "expires_at": attempt.expires_at,
    }


def expire_instagram_oauth_attempts(
    db: Session,
    *,
    business_id: int | None = None,
) -> int:
    query = db.query(InstagramOAuthAttempt).filter(
        InstagramOAuthAttempt.status.in_(("pending", "processing", "candidate_ready")),
        InstagramOAuthAttempt.expires_at <= utc_now(),
    )
    if business_id is not None:
        query = query.filter(InstagramOAuthAttempt.business_id == business_id)
    attempts = query.with_for_update().all()
    now = utc_now()
    for attempt in attempts:
        attempt.status = "expired"
        attempt.invalidated_at = now
        attempt.safe_error_code = "attempt_expired"
        attempt.safe_error_message = "Instagram authorization expired"
        _clear_candidate_credentials(attempt)
    db.flush()
    return len(attempts)


def invalidate_instagram_oauth_attempts(
    db: Session,
    *,
    business_id: int,
    safe_code: str,
) -> int:
    attempts = (
        db.query(InstagramOAuthAttempt)
        .filter(
            InstagramOAuthAttempt.business_id == business_id,
            InstagramOAuthAttempt.status.in_(("pending", "processing", "candidate_ready")),
        )
        .with_for_update()
        .all()
    )
    now = utc_now()
    for attempt in attempts:
        attempt.status = "cancelled"
        attempt.invalidated_at = now
        attempt.safe_error_code = safe_code[:80]
        attempt.safe_error_message = "Instagram authorization was cancelled"
        _clear_candidate_credentials(attempt)
    db.flush()
    return len(attempts)


def retry_instagram_candidate_webhook(
    db: Session,
    *,
    business_id: int,
    attempt_id: int,
    settings: Settings | None = None,
) -> InstagramOAuthAttempt:
    settings = settings or get_settings()
    attempt = (
        db.query(InstagramOAuthAttempt)
        .filter(
            InstagramOAuthAttempt.id == attempt_id,
            InstagramOAuthAttempt.business_id == business_id,
            InstagramOAuthAttempt.status == "candidate_ready",
        )
        .with_for_update()
        .first()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Instagram candidate not found")
    if not (
        attempt.candidate_external_account_id
        and attempt.candidate_encrypted_access_token
        and attempt.candidate_encryption_key_version
    ):
        raise HTTPException(
            status_code=409, detail="Instagram candidate credentials are unavailable"
        )
    try:
        token = decrypt_secret(
            attempt.candidate_encrypted_access_token,
            attempt.candidate_encryption_key_version,
            settings=settings,
        )
    except IntegrationCryptoError as exc:
        raise HTTPException(
            status_code=503, detail="Instagram credentials are unavailable"
        ) from exc
    account_id = attempt.candidate_external_account_id
    db.commit()
    try:
        subscribe_instagram_messages_webhook(account_id, token, settings=settings)
        error = None
    except InstagramLoginProviderError as exc:
        error = exc
    attempt = db.get(InstagramOAuthAttempt, attempt_id)
    if attempt is None or attempt.status != "candidate_ready":
        raise HTTPException(status_code=409, detail="Instagram candidate is no longer active")
    attempt.webhook_subscription_status = "failed" if error else "subscribed"
    attempt.safe_error_code = error.safe_code if error else None
    attempt.safe_error_message = error.safe_message if error else None
    db.flush()
    return attempt


def decide_instagram_oauth_candidate(
    db: Session,
    *,
    business_id: int,
    attempt_id: int,
    actor: User,
    approve: bool,
    reason: str,
) -> tuple[InstagramOAuthAttempt, BusinessChannelIntegration | None]:
    attempt = (
        db.query(InstagramOAuthAttempt)
        .filter(
            InstagramOAuthAttempt.id == attempt_id,
            InstagramOAuthAttempt.business_id == business_id,
        )
        .with_for_update()
        .first()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Instagram candidate not found")
    if attempt.status != "candidate_ready":
        raise HTTPException(status_code=409, detail="Instagram candidate is not awaiting review")
    if _as_utc(attempt.expires_at) <= utc_now():
        attempt.status = "expired"
        attempt.invalidated_at = utc_now()
        attempt.safe_error_code = "attempt_expired"
        attempt.safe_error_message = "Instagram authorization expired"
        _clear_candidate_credentials(attempt)
        db.commit()
        raise HTTPException(status_code=410, detail="Instagram candidate expired")
    control = (
        db.query(BusinessChannelControl)
        .filter(
            BusinessChannelControl.id == attempt.channel_control_id,
            BusinessChannelControl.business_id == business_id,
            BusinessChannelControl.channel == INSTAGRAM_CHANNEL,
        )
        .with_for_update()
        .first()
    )
    if control is None:
        raise HTTPException(status_code=409, detail="Instagram channel control is unavailable")
    now = utc_now()
    integration = get_instagram_integration(db, business_id=business_id)
    if not approve:
        attempt.status = "rejected"
        attempt.invalidated_at = now
        attempt.safe_error_code = "owner_rejected"
        attempt.safe_error_message = "Instagram candidate was rejected by Owner"
        _clear_candidate_credentials(attempt)
        if control.status == "pending_approval":
            control.status = "available"
            control.requested_by_user_id = None
            control.requested_at = None
            control.updated_by_user_id = actor.id
            control.last_reason = reason
        db.flush()
        return attempt, integration

    account_id = attempt.candidate_external_account_id
    if not account_id or not attempt.candidate_encrypted_access_token:
        raise HTTPException(
            status_code=409, detail="Instagram candidate credentials are unavailable"
        )
    if attempt.webhook_subscription_status != "subscribed":
        raise HTTPException(
            status_code=409,
            detail="Instagram webhook must be retried successfully before approval",
        )
    conflict = (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.provider == INSTAGRAM_PROVIDER,
            BusinessChannelIntegration.external_account_id == account_id,
            BusinessChannelIntegration.business_id != business_id,
        )
        .with_for_update()
        .first()
    )
    if conflict is not None:
        raise HTTPException(status_code=409, detail="Instagram account belongs to another business")

    old_account_id = integration.external_account_id if integration else None
    if integration is None:
        integration = BusinessChannelIntegration(
            business_id=business_id,
            channel=INSTAGRAM_CHANNEL,
            provider=INSTAGRAM_PROVIDER,
            external_account_id=account_id,
        )
        db.add(integration)
    elif old_account_id != account_id:
        # Retire routing identifiers before replacing the account so a sender
        # identifier reused by another Instagram account cannot reopen an old thread.
        conversations = (
            db.query(Conversation)
            .filter(
                Conversation.business_id == business_id,
                Conversation.channel == INSTAGRAM_CHANNEL,
                Conversation.external_user_id.is_not(None),
            )
            .all()
        )
        for conversation in conversations:
            conversation.external_user_id = None
            conversation.external_conversation_id = f"retired:{old_account_id}:{conversation.id}"[
                :255
            ]
            conversation.status = "closed"
            conversation.updated_at = now

    integration.external_account_id = account_id
    integration.external_account_name = attempt.candidate_external_account_name
    integration.encrypted_access_token = attempt.candidate_encrypted_access_token
    integration.encryption_key_version = attempt.candidate_encryption_key_version
    integration.token_type = "bearer"
    integration.token_expires_at = attempt.candidate_token_expires_at
    integration.token_last_refreshed_at = now
    integration.granted_scopes_json = attempt.candidate_granted_scopes
    integration.integration_status = "connected"
    integration.provider_status = "webhook_subscribed"
    integration.connected_at = integration.connected_at or now
    integration.disconnected_at = None
    integration.last_verified_at = now
    integration.last_success_at = now
    integration.last_error_at = None
    integration.last_error_code = None
    integration.last_error_subcode = None
    integration.last_error_type = None
    integration.safe_error_message = None
    integration.metadata_json = attempt.metadata_json
    integration.health_status = "unknown"
    integration.last_health_check_at = None
    integration.next_health_check_at = now + timedelta(minutes=(integration.id or 1) % 60 + 1)
    integration.consecutive_health_failures = 0
    integration.health_error_code = None
    integration.health_safe_error_message = None
    integration.health_metadata_json = None
    db.flush()

    if old_account_id and old_account_id != account_id:
        db.query(InstagramRemoteMedia).filter(
            InstagramRemoteMedia.integration_id == integration.id,
            InstagramRemoteMedia.remote_status == "available",
        ).update(
            {
                InstagramRemoteMedia.remote_status: "unavailable",
                InstagramRemoteMedia.unavailable_at: now,
                InstagramRemoteMedia.last_error_code: "instagram_account_replaced",
                InstagramRemoteMedia.updated_at: now,
            },
            synchronize_session=False,
        )
        sync_state = (
            db.query(InstagramMediaSyncState)
            .filter(InstagramMediaSyncState.integration_id == integration.id)
            .first()
        )
        if sync_state is not None:
            sync_state.status = "idle"
            sync_state.run_id = None
            sync_state.after_cursor = None

    if control.status == "pending_approval":
        control.status = "approved"
        control.approved_by_user_id = actor.id
        control.approved_at = now
        control.integrated_delivery_enabled = False
        control.automation_enabled = False
    control.connection_mode = "oauth"
    control.updated_by_user_id = actor.id
    control.last_reason = reason
    attempt.status = "approved"
    attempt.invalidated_at = now
    _clear_candidate_credentials(attempt)
    db.flush()
    if get_settings().instagram_media_sync_enabled:
        from app.services.instagram_media_sync_service import enqueue_instagram_media_sync

        enqueue_instagram_media_sync(
            db,
            business_id=business_id,
            origin="system",
        )
    return attempt, integration
