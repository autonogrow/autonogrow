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
from app.models.business import Business
from app.models.business_channel_control import BusinessChannelControl
from app.models.business_channel_integration import BusinessChannelIntegration
from app.models.business_user import BusinessUser
from app.models.conversation import Conversation
from app.models.user import User
from app.models.whatsapp_embedded_signup_attempt import WhatsAppEmbeddedSignupAttempt
from app.services.channel_control_service import utc_now
from app.services.integration_crypto_service import (
    IntegrationCryptoError,
    decrypt_secret,
    encrypt_secret,
    validate_encryption_configuration,
)
from app.services.whatsapp_embedded_signup_provider import (
    META_ID_PATTERN,
    WHATSAPP_EMBEDDED_SIGNUP_EVENT_TYPE,
    WHATSAPP_EMBEDDED_SIGNUP_FINISH_EVENT,
    WHATSAPP_EMBEDDED_SIGNUP_SDK_URL,
    WhatsAppEmbeddedSignupProviderError,
    exchange_whatsapp_embedded_signup_code,
    inspect_whatsapp_business_token,
    redact_display_phone_number,
    subscribe_app_to_whatsapp_waba,
    verify_whatsapp_embedded_signup_assets,
)

WHATSAPP_CHANNEL = "whatsapp"
WHATSAPP_PROVIDER = "whatsapp"
CANDIDATE_REVIEW_HOURS = 72


def _as_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def whatsapp_session_fingerprint(session_token: str, *, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if not session_token or not settings.session_secret:
        raise HTTPException(status_code=401, detail="Authentication session is unavailable")
    return hmac.new(
        settings.session_secret.encode("utf-8"),
        f"whatsapp-embedded-signup:{session_token}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _ensure_signup_configured(settings: Settings) -> None:
    if not settings.whatsapp_embedded_signup_enabled:
        raise HTTPException(status_code=503, detail="WhatsApp Embedded Signup is disabled")
    required = (
        settings.meta_app_id.strip(),
        settings.meta_app_secret.strip(),
        settings.whatsapp_embedded_signup_config_id.strip(),
        settings.whatsapp_embedded_signup_graph_api_version.strip(),
    )
    if (
        not all(required)
        or META_ID_PATTERN.fullmatch(settings.meta_app_id.strip()) is None
        or META_ID_PATTERN.fullmatch(settings.whatsapp_embedded_signup_config_id.strip()) is None
        or re.fullmatch(r"v\d+\.\d+", settings.whatsapp_embedded_signup_graph_api_version.strip())
        is None
    ):
        raise HTTPException(status_code=503, detail="WhatsApp Embedded Signup is unavailable")
    try:
        validate_encryption_configuration(settings, required=True)
    except IntegrationCryptoError as exc:
        raise HTTPException(
            status_code=503, detail="WhatsApp Embedded Signup is unavailable"
        ) from exc


def get_whatsapp_integration(db: Session, *, business_id: int) -> BusinessChannelIntegration | None:
    return (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.business_id == business_id,
            BusinessChannelIntegration.channel == WHATSAPP_CHANNEL,
            BusinessChannelIntegration.provider == WHATSAPP_PROVIDER,
        )
        .first()
    )


def _purpose_for_business(db: Session, *, business_id: int, requested_purpose: str | None) -> str:
    integration = get_whatsapp_integration(db, business_id=business_id)
    derived = "initial_connection" if integration is None else "reconnect"
    if requested_purpose is None:
        return derived
    if requested_purpose not in {"initial_connection", "reconnect", "replacement"}:
        raise HTTPException(status_code=422, detail="Invalid WhatsApp connection purpose")
    if integration is None and requested_purpose != "initial_connection":
        raise HTTPException(status_code=409, detail="WhatsApp has no integration to replace")
    if integration is not None and requested_purpose == "initial_connection":
        raise HTTPException(status_code=409, detail="WhatsApp is already configured")
    return requested_purpose


def start_whatsapp_embedded_signup(
    db: Session,
    *,
    business: Business,
    control: BusinessChannelControl,
    actor: User,
    actor_role: str,
    session_token: str,
    requested_purpose: str | None = None,
    settings: Settings | None = None,
) -> tuple[WhatsAppEmbeddedSignupAttempt, str, dict]:
    settings = settings or get_settings()
    _ensure_signup_configured(settings)
    expire_whatsapp_signup_attempts(db, business_id=business.id)
    if control.channel != WHATSAPP_CHANNEL:
        raise HTTPException(status_code=404, detail="WhatsApp channel control not found")
    if not actor.is_owner and not (
        actor_role == "business_admin" and control.connector_policy == "business_admin"
    ):
        raise HTTPException(status_code=403, detail="You cannot connect assets for this channel")
    purpose = _purpose_for_business(
        db, business_id=business.id, requested_purpose=requested_purpose
    )
    if purpose == "initial_connection" and control.status != "available":
        raise HTTPException(status_code=409, detail="WhatsApp is not available for connection")
    if purpose != "initial_connection" and control.status not in {"available", "approved"}:
        raise HTTPException(status_code=409, detail="WhatsApp channel is not reconnectable")
    if (
        db.query(WhatsAppEmbeddedSignupAttempt.id)
        .filter(
            WhatsAppEmbeddedSignupAttempt.business_id == business.id,
            WhatsAppEmbeddedSignupAttempt.status == "candidate_ready",
        )
        .first()
        is not None
    ):
        raise HTTPException(status_code=409, detail="A WhatsApp candidate awaits Owner review")
    if (
        db.query(WhatsAppEmbeddedSignupAttempt.id)
        .filter(
            WhatsAppEmbeddedSignupAttempt.business_id == business.id,
            WhatsAppEmbeddedSignupAttempt.user_id == actor.id,
            WhatsAppEmbeddedSignupAttempt.status == "processing",
        )
        .first()
        is not None
    ):
        raise HTTPException(status_code=409, detail="WhatsApp signup is already processing")
    now = utc_now()
    db.query(WhatsAppEmbeddedSignupAttempt).filter(
        WhatsAppEmbeddedSignupAttempt.business_id == business.id,
        WhatsAppEmbeddedSignupAttempt.user_id == actor.id,
        WhatsAppEmbeddedSignupAttempt.purpose == purpose,
        WhatsAppEmbeddedSignupAttempt.status == "pending",
    ).update(
        {
            WhatsAppEmbeddedSignupAttempt.status: "cancelled",
            WhatsAppEmbeddedSignupAttempt.invalidated_at: now,
            WhatsAppEmbeddedSignupAttempt.safe_error_code: "superseded",
            WhatsAppEmbeddedSignupAttempt.safe_error_message: "A newer signup was started",
        },
        synchronize_session=False,
    )
    state = token_urlsafe(48)
    attempt = WhatsAppEmbeddedSignupAttempt(
        business_id=business.id,
        user_id=actor.id,
        channel_control_id=control.id,
        purpose=purpose,
        status="pending",
        state_hash=_hash_value(state),
        session_fingerprint_hash=whatsapp_session_fingerprint(session_token, settings=settings),
        created_at=now,
        expires_at=now + timedelta(seconds=settings.whatsapp_embedded_signup_attempt_ttl_seconds),
        metadata_json=json.dumps({"contract": "meta_embedded_signup_default"}, sort_keys=True),
    )
    db.add(attempt)
    db.flush()
    public_configuration = {
        "app_id": settings.meta_app_id.strip(),
        "config_id": settings.whatsapp_embedded_signup_config_id.strip(),
        "graph_api_version": settings.whatsapp_embedded_signup_graph_api_version.strip(),
        "sdk_url": WHATSAPP_EMBEDDED_SIGNUP_SDK_URL,
        "event_type": WHATSAPP_EMBEDDED_SIGNUP_EVENT_TYPE,
        "finish_event": WHATSAPP_EMBEDDED_SIGNUP_FINISH_EVENT,
        "login_parameters": {
            "response_type": "code",
            "override_default_response_type": True,
            "extras": {"setup": {}},
        },
    }
    return attempt, state, public_configuration


def _clear_candidate(attempt: WhatsAppEmbeddedSignupAttempt) -> None:
    attempt.candidate_meta_business_id = None
    attempt.candidate_waba_id = None
    attempt.candidate_phone_number_id = None
    attempt.candidate_encrypted_access_token = None
    attempt.candidate_encryption_key_version = None
    attempt.candidate_token_expires_at = None
    attempt.candidate_granted_scopes = None
    attempt.metadata_json = None


def _fail_processing_attempt(
    db: Session, *, attempt_id: int, safe_code: str, safe_message: str
) -> WhatsAppEmbeddedSignupAttempt:
    attempt = db.get(WhatsAppEmbeddedSignupAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=409, detail="WhatsApp signup is unavailable")
    if attempt.status == "processing":
        attempt.status = "failed"
        attempt.invalidated_at = utc_now()
        attempt.safe_error_code = safe_code[:80]
        attempt.safe_error_message = safe_message[:500]
        _clear_candidate(attempt)
        db.commit()
        db.refresh(attempt)
    return attempt


def consume_whatsapp_signup_state(
    db: Session,
    *,
    business_id: int,
    opaque_state: str,
    actor: User,
    session_token: str,
    settings: Settings | None = None,
) -> WhatsAppEmbeddedSignupAttempt:
    settings = settings or get_settings()
    if not 32 <= len(opaque_state) <= 512:
        raise HTTPException(status_code=400, detail="Invalid WhatsApp signup")
    attempt = (
        db.query(WhatsAppEmbeddedSignupAttempt)
        .filter(WhatsAppEmbeddedSignupAttempt.state_hash == _hash_value(opaque_state))
        .first()
    )
    if attempt is None or attempt.status != "pending":
        raise HTTPException(status_code=409, detail="WhatsApp signup was already used")
    if attempt.business_id != business_id:
        raise HTTPException(status_code=403, detail="WhatsApp signup context mismatch")
    now = utc_now()
    if _as_utc(attempt.expires_at) <= now:
        attempt.status = "expired"
        attempt.invalidated_at = now
        attempt.safe_error_code = "state_expired"
        attempt.safe_error_message = "WhatsApp signup expired"
        db.commit()
        raise HTTPException(status_code=410, detail="WhatsApp signup expired")
    expected = whatsapp_session_fingerprint(session_token, settings=settings)
    if attempt.user_id != actor.id or not hmac.compare_digest(
        attempt.session_fingerprint_hash, expected
    ):
        raise HTTPException(status_code=403, detail="WhatsApp signup session mismatch")
    control = db.get(BusinessChannelControl, attempt.channel_control_id)
    if control is None or control.business_id != business_id or control.channel != WHATSAPP_CHANNEL:
        raise HTTPException(status_code=400, detail="Invalid WhatsApp signup")
    if not actor.is_owner:
        membership = (
            db.query(BusinessUser.id)
            .filter(
                BusinessUser.business_id == business_id,
                BusinessUser.user_id == actor.id,
                BusinessUser.role == "business_admin",
                BusinessUser.active.is_(True),
            )
            .first()
        )
        if membership is None:
            raise HTTPException(status_code=403, detail="Business administrator access required")
    updated = (
        db.query(WhatsAppEmbeddedSignupAttempt)
        .filter(
            WhatsAppEmbeddedSignupAttempt.id == attempt.id,
            WhatsAppEmbeddedSignupAttempt.status == "pending",
        )
        .update(
            {
                WhatsAppEmbeddedSignupAttempt.status: "processing",
                WhatsAppEmbeddedSignupAttempt.consumed_at: now,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="WhatsApp signup was already used")
    db.commit()
    consumed = db.get(WhatsAppEmbeddedSignupAttempt, attempt.id)
    if consumed is None:
        raise HTTPException(status_code=409, detail="WhatsApp signup is unavailable")
    return consumed


def complete_whatsapp_embedded_signup(
    db: Session,
    *,
    business_id: int,
    opaque_state: str,
    authorization_code: str | None,
    event_type: str,
    event_name: str,
    meta_business_id: str | None,
    waba_id: str | None,
    phone_number_id: str | None,
    actor: User,
    session_token: str,
    settings: Settings | None = None,
) -> WhatsAppEmbeddedSignupAttempt:
    settings = settings or get_settings()
    _ensure_signup_configured(settings)
    attempt = consume_whatsapp_signup_state(
        db,
        business_id=business_id,
        opaque_state=opaque_state,
        actor=actor,
        session_token=session_token,
        settings=settings,
    )
    if event_type != WHATSAPP_EMBEDDED_SIGNUP_EVENT_TYPE:
        return _fail_processing_attempt(
            db,
            attempt_id=attempt.id,
            safe_code="sdk_event_invalid",
            safe_message="Meta returned an invalid signup event",
        )
    if event_name == "CANCEL":
        attempt.status = "cancelled"
        attempt.invalidated_at = utc_now()
        attempt.safe_error_code = "signup_cancelled"
        attempt.safe_error_message = "WhatsApp signup was cancelled"
        db.commit()
        db.refresh(attempt)
        return attempt
    if event_name != WHATSAPP_EMBEDDED_SIGNUP_FINISH_EVENT:
        return _fail_processing_attempt(
            db,
            attempt_id=attempt.id,
            safe_code="signup_variant_unsupported",
            safe_message="This WhatsApp signup variant is not supported yet",
        )
    if not authorization_code or not 4 <= len(authorization_code) <= 4096:
        return _fail_processing_attempt(
            db,
            attempt_id=attempt.id,
            safe_code="authorization_code_missing",
            safe_message="WhatsApp authorization code was not received",
        )
    if not meta_business_id or not waba_id or not phone_number_id:
        return _fail_processing_attempt(
            db,
            attempt_id=attempt.id,
            safe_code="sdk_assets_missing",
            safe_message="Meta did not return all required WhatsApp assets",
        )
    try:
        raw_token = exchange_whatsapp_embedded_signup_code(authorization_code, settings=settings)
        token = inspect_whatsapp_business_token(
            raw_token, expected_waba_id=waba_id, settings=settings
        )
        assets = verify_whatsapp_embedded_signup_assets(
            raw_token,
            meta_business_id=meta_business_id,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            settings=settings,
        )
        integration_conflict = (
            db.query(BusinessChannelIntegration.id)
            .filter(
                BusinessChannelIntegration.provider == WHATSAPP_PROVIDER,
                BusinessChannelIntegration.business_id != business_id,
                (
                    (BusinessChannelIntegration.external_account_id == assets.phone_number_id)
                    | (BusinessChannelIntegration.provider_account_id == assets.waba_id)
                ),
            )
            .first()
        )
        candidate_conflict = (
            db.query(WhatsAppEmbeddedSignupAttempt.id)
            .filter(
                WhatsAppEmbeddedSignupAttempt.status == "candidate_ready",
                WhatsAppEmbeddedSignupAttempt.business_id != business_id,
                (
                    (
                        WhatsAppEmbeddedSignupAttempt.candidate_phone_number_id
                        == assets.phone_number_id
                    )
                    | (WhatsAppEmbeddedSignupAttempt.candidate_waba_id == assets.waba_id)
                ),
            )
            .first()
        )
        if integration_conflict is not None or candidate_conflict is not None:
            return _fail_processing_attempt(
                db,
                attempt_id=attempt.id,
                safe_code="asset_already_linked",
                safe_message="WhatsApp assets are already linked to another account",
            )
        db.commit()
    except WhatsAppEmbeddedSignupProviderError as exc:
        return _fail_processing_attempt(
            db,
            attempt_id=attempt.id,
            safe_code=exc.safe_code,
            safe_message=exc.safe_message,
        )
    subscription_error: WhatsAppEmbeddedSignupProviderError | None = None
    try:
        subscribe_app_to_whatsapp_waba(assets.waba_id, raw_token, settings=settings)
    except WhatsAppEmbeddedSignupProviderError as exc:
        subscription_error = exc
    try:
        ciphertext, key_version = encrypt_secret(raw_token, settings=settings)
    except IntegrationCryptoError:
        return _fail_processing_attempt(
            db,
            attempt_id=attempt.id,
            safe_code="credential_encryption_failed",
            safe_message="WhatsApp credentials could not be protected",
        )
    refreshed = db.get(WhatsAppEmbeddedSignupAttempt, attempt.id)
    if refreshed is None or refreshed.status != "processing":
        raise HTTPException(status_code=409, detail="WhatsApp signup is no longer active")
    attempt = refreshed
    control = db.get(BusinessChannelControl, attempt.channel_control_id)
    if control is None or control.status not in {"available", "approved"}:
        return _fail_processing_attempt(
            db,
            attempt_id=attempt.id,
            safe_code="channel_access_changed",
            safe_message="WhatsApp channel access changed during signup",
        )
    current = get_whatsapp_integration(db, business_id=business_id)
    attempt.purpose = (
        "initial_connection"
        if current is None
        else (
            "reconnect" if current.external_account_id == assets.phone_number_id else "replacement"
        )
    )
    attempt.status = "candidate_ready"
    review_expiry = utc_now() + timedelta(hours=CANDIDATE_REVIEW_HOURS)
    if token.expires_at is not None:
        review_expiry = min(review_expiry, _as_utc(token.expires_at))
    attempt.expires_at = review_expiry
    attempt.candidate_meta_business_id = assets.meta_business_id
    attempt.candidate_waba_id = assets.waba_id
    attempt.candidate_phone_number_id = assets.phone_number_id
    attempt.candidate_display_phone_number_redacted = redact_display_phone_number(
        assets.display_phone_number
    )
    attempt.candidate_verified_name = assets.verified_name
    attempt.candidate_phone_status = assets.phone_status
    attempt.candidate_encrypted_access_token = ciphertext
    attempt.candidate_encryption_key_version = key_version
    attempt.candidate_token_expires_at = token.expires_at
    attempt.candidate_granted_scopes = json.dumps(list(token.granted_scopes))
    attempt.app_subscription_status = "failed" if subscription_error else "subscribed"
    attempt.phone_registration_status = assets.registration_status
    error = subscription_error
    if error is None and assets.registration_status != "registered":
        attempt.safe_error_code = "phone_registration_required"
        attempt.safe_error_message = "The WhatsApp phone number requires registration in Meta"
    else:
        attempt.safe_error_code = error.safe_code if error else None
        attempt.safe_error_message = error.safe_message if error else None
    attempt.metadata_json = json.dumps(
        {"token_type": token.token_type, "contract": "meta_embedded_signup_default"},
        sort_keys=True,
    )
    if control.status == "available":
        control.status = "pending_approval"
        control.connection_mode = "embedded_signup"
        control.requested_by_user_id = actor.id
        control.requested_at = utc_now()
        control.approved_by_user_id = None
        control.approved_at = None
        control.integrated_delivery_enabled = False
        control.automation_enabled = False
        control.updated_by_user_id = actor.id
        control.last_reason = "WhatsApp candidate awaiting Owner approval"
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return _fail_processing_attempt(
            db,
            attempt_id=attempt.id,
            safe_code="asset_already_linked",
            safe_message="WhatsApp assets are already linked",
        )
    db.refresh(attempt)
    return attempt


def serialize_whatsapp_signup_attempt(attempt: WhatsAppEmbeddedSignupAttempt) -> dict:
    scopes: list[str] = []
    try:
        parsed = json.loads(attempt.candidate_granted_scopes or "[]")
        if isinstance(parsed, list):
            scopes = [str(item) for item in parsed]
    except ValueError:
        pass
    return {
        "id": attempt.id,
        "purpose": attempt.purpose,
        "status": attempt.status,
        "candidate_verified_name": attempt.candidate_verified_name,
        "candidate_display_phone_number_redacted": (
            attempt.candidate_display_phone_number_redacted
        ),
        "candidate_phone_status": attempt.candidate_phone_status,
        "candidate_granted_scopes": scopes,
        "app_subscription_status": attempt.app_subscription_status,
        "phone_registration_status": attempt.phone_registration_status,
        "created_at": attempt.created_at,
        "expires_at": attempt.expires_at,
        "candidate_token_expires_at": attempt.candidate_token_expires_at,
        "safe_error_code": attempt.safe_error_code,
        "safe_error_message": attempt.safe_error_message,
    }


def expire_whatsapp_signup_attempts(db: Session, *, business_id: int | None = None) -> int:
    query = db.query(WhatsAppEmbeddedSignupAttempt).filter(
        WhatsAppEmbeddedSignupAttempt.status.in_(("pending", "processing", "candidate_ready")),
        WhatsAppEmbeddedSignupAttempt.expires_at <= utc_now(),
    )
    if business_id is not None:
        query = query.filter(WhatsAppEmbeddedSignupAttempt.business_id == business_id)
    attempts = query.with_for_update().all()
    now = utc_now()
    for attempt in attempts:
        attempt.status = "expired"
        attempt.invalidated_at = now
        attempt.safe_error_code = "attempt_expired"
        attempt.safe_error_message = "WhatsApp signup expired"
        _clear_candidate(attempt)
    if attempts:
        db.flush()
    return len(attempts)


def invalidate_whatsapp_signup_attempts(db: Session, *, business_id: int, safe_code: str) -> int:
    attempts = (
        db.query(WhatsAppEmbeddedSignupAttempt)
        .filter(
            WhatsAppEmbeddedSignupAttempt.business_id == business_id,
            WhatsAppEmbeddedSignupAttempt.status.in_(("pending", "processing", "candidate_ready")),
        )
        .with_for_update()
        .all()
    )
    now = utc_now()
    for attempt in attempts:
        attempt.status = "cancelled"
        attempt.invalidated_at = now
        attempt.safe_error_code = safe_code[:80]
        attempt.safe_error_message = "WhatsApp signup was cancelled"
        _clear_candidate(attempt)
    if attempts:
        db.flush()
    return len(attempts)


def retry_whatsapp_candidate_setup(
    db: Session,
    *,
    business_id: int,
    attempt_id: int,
    settings: Settings | None = None,
) -> WhatsAppEmbeddedSignupAttempt:
    settings = settings or get_settings()
    attempt = (
        db.query(WhatsAppEmbeddedSignupAttempt)
        .filter(
            WhatsAppEmbeddedSignupAttempt.id == attempt_id,
            WhatsAppEmbeddedSignupAttempt.business_id == business_id,
            WhatsAppEmbeddedSignupAttempt.status == "candidate_ready",
        )
        .with_for_update()
        .first()
    )
    if (
        attempt is None
        or not attempt.candidate_encrypted_access_token
        or not attempt.candidate_encryption_key_version
        or not attempt.candidate_meta_business_id
        or not attempt.candidate_waba_id
        or not attempt.candidate_phone_number_id
    ):
        raise HTTPException(status_code=409, detail="WhatsApp candidate is unavailable")
    try:
        token = decrypt_secret(
            attempt.candidate_encrypted_access_token,
            attempt.candidate_encryption_key_version,
            settings=settings,
        )
        inspected = inspect_whatsapp_business_token(
            token, expected_waba_id=attempt.candidate_waba_id, settings=settings
        )
        assets = verify_whatsapp_embedded_signup_assets(
            token,
            meta_business_id=attempt.candidate_meta_business_id,
            waba_id=attempt.candidate_waba_id,
            phone_number_id=attempt.candidate_phone_number_id,
            settings=settings,
        )
        subscribe_app_to_whatsapp_waba(attempt.candidate_waba_id, token, settings=settings)
    except (IntegrationCryptoError, WhatsAppEmbeddedSignupProviderError) as exc:
        safe_code = (
            exc.safe_code
            if isinstance(exc, WhatsAppEmbeddedSignupProviderError)
            else "credential_decryption_failed"
        )
        safe_message = (
            exc.safe_message
            if isinstance(exc, WhatsAppEmbeddedSignupProviderError)
            else "WhatsApp credentials could not be read"
        )
        attempt.app_subscription_status = "failed"
        attempt.safe_error_code = safe_code
        attempt.safe_error_message = safe_message
        db.flush()
        return attempt
    attempt.candidate_verified_name = assets.verified_name
    attempt.candidate_display_phone_number_redacted = redact_display_phone_number(
        assets.display_phone_number
    )
    attempt.candidate_phone_status = assets.phone_status
    attempt.candidate_granted_scopes = json.dumps(list(inspected.granted_scopes))
    attempt.app_subscription_status = "subscribed"
    attempt.phone_registration_status = assets.registration_status
    if assets.registration_status == "registered":
        attempt.safe_error_code = None
        attempt.safe_error_message = None
    else:
        attempt.safe_error_code = "phone_registration_required"
        attempt.safe_error_message = "The WhatsApp phone number requires registration in Meta"
    db.flush()
    return attempt


def decide_whatsapp_signup_candidate(
    db: Session,
    *,
    business_id: int,
    attempt_id: int,
    actor: User,
    approve: bool,
    reason: str,
) -> tuple[WhatsAppEmbeddedSignupAttempt, BusinessChannelIntegration | None]:
    attempt = (
        db.query(WhatsAppEmbeddedSignupAttempt)
        .filter(
            WhatsAppEmbeddedSignupAttempt.id == attempt_id,
            WhatsAppEmbeddedSignupAttempt.business_id == business_id,
        )
        .with_for_update()
        .first()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="WhatsApp candidate not found")
    if attempt.status != "candidate_ready":
        raise HTTPException(status_code=409, detail="WhatsApp candidate is not awaiting review")
    if _as_utc(attempt.expires_at) <= utc_now():
        attempt.status = "expired"
        attempt.invalidated_at = utc_now()
        _clear_candidate(attempt)
        db.commit()
        raise HTTPException(status_code=410, detail="WhatsApp candidate expired")
    control = (
        db.query(BusinessChannelControl)
        .filter(
            BusinessChannelControl.id == attempt.channel_control_id,
            BusinessChannelControl.business_id == business_id,
            BusinessChannelControl.channel == WHATSAPP_CHANNEL,
        )
        .with_for_update()
        .first()
    )
    if control is None:
        raise HTTPException(status_code=409, detail="WhatsApp channel control is unavailable")
    integration = get_whatsapp_integration(db, business_id=business_id)
    now = utc_now()
    if not approve:
        attempt.status = "rejected"
        attempt.invalidated_at = now
        attempt.safe_error_code = "owner_rejected"
        attempt.safe_error_message = "WhatsApp candidate was rejected by Owner"
        _clear_candidate(attempt)
        if control.status == "pending_approval":
            control.status = "available"
            control.requested_by_user_id = None
            control.requested_at = None
            control.updated_by_user_id = actor.id
            control.last_reason = reason
        db.flush()
        return attempt, integration
    if attempt.app_subscription_status != "subscribed":
        raise HTTPException(status_code=409, detail="WhatsApp app subscription must be confirmed")
    if attempt.phone_registration_status != "registered":
        raise HTTPException(status_code=409, detail="WhatsApp phone registration must be confirmed")
    phone_id = attempt.candidate_phone_number_id
    waba_id = attempt.candidate_waba_id
    if not phone_id or not waba_id or not attempt.candidate_encrypted_access_token:
        raise HTTPException(
            status_code=409, detail="WhatsApp candidate credentials are unavailable"
        )
    conflict = (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.provider == WHATSAPP_PROVIDER,
            BusinessChannelIntegration.business_id != business_id,
            (
                (BusinessChannelIntegration.external_account_id == phone_id)
                | (BusinessChannelIntegration.provider_account_id == waba_id)
            ),
        )
        .with_for_update()
        .first()
    )
    if conflict is not None:
        raise HTTPException(status_code=409, detail="WhatsApp assets belong to another account")
    old_phone_id = integration.external_account_id if integration else None
    if integration is None:
        integration = BusinessChannelIntegration(
            business_id=business_id,
            channel=WHATSAPP_CHANNEL,
            provider=WHATSAPP_PROVIDER,
            external_account_id=phone_id,
        )
        db.add(integration)
    elif old_phone_id != phone_id:
        conversations = (
            db.query(Conversation)
            .filter(
                Conversation.business_id == business_id,
                Conversation.channel == WHATSAPP_CHANNEL,
                Conversation.external_user_id.is_not(None),
            )
            .all()
        )
        for conversation in conversations:
            conversation.external_user_id = (
                f"retired:{old_phone_id}:{conversation.external_user_id}"[:255]
            )
            conversation.external_conversation_id = f"retired:{old_phone_id}:{conversation.id}"[
                :255
            ]
            conversation.status = "closed"
            conversation.updated_at = now
    metadata: dict = {}
    try:
        parsed = json.loads(attempt.metadata_json or "{}")
        if isinstance(parsed, dict):
            metadata = parsed
    except ValueError:
        pass
    integration.external_account_id = phone_id
    integration.provider_account_id = waba_id
    integration.external_account_name = attempt.candidate_verified_name
    integration.encrypted_access_token = attempt.candidate_encrypted_access_token
    integration.encryption_key_version = attempt.candidate_encryption_key_version
    integration.token_type = str(metadata.get("token_type") or "business_integration_system_user")[
        :40
    ]
    integration.token_expires_at = attempt.candidate_token_expires_at
    integration.token_last_refreshed_at = now
    integration.granted_scopes_json = attempt.candidate_granted_scopes
    integration.integration_status = "connected"
    integration.provider_status = "waba_subscribed"
    integration.connected_at = integration.connected_at or now
    integration.disconnected_at = None
    integration.last_verified_at = now
    integration.last_success_at = now
    integration.last_error_at = None
    integration.last_error_code = None
    integration.last_error_subcode = None
    integration.last_error_type = None
    integration.safe_error_message = None
    integration.metadata_json = json.dumps(
        {
            "meta_business_id": attempt.candidate_meta_business_id,
            "display_phone_number_redacted": (attempt.candidate_display_phone_number_redacted),
            "phone_status": attempt.candidate_phone_status,
            "phone_registration_status": attempt.phone_registration_status,
        },
        sort_keys=True,
    )
    integration.health_status = "unknown"
    integration.last_health_check_at = None
    integration.next_health_check_at = now + timedelta(minutes=(integration.id or 1) % 60 + 1)
    integration.consecutive_health_failures = 0
    integration.health_error_code = None
    integration.health_safe_error_message = None
    integration.health_metadata_json = None
    db.flush()
    control.status = "approved"
    control.connection_mode = "embedded_signup"
    control.approved_by_user_id = actor.id
    control.approved_at = now
    control.integrated_delivery_enabled = False
    control.automation_enabled = False
    control.updated_by_user_id = actor.id
    control.last_reason = reason
    attempt.status = "approved"
    attempt.invalidated_at = now
    _clear_candidate(attempt)
    db.flush()
    return attempt, integration
