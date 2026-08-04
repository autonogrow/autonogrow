import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import Settings, get_settings
from app.models import (
    Business,
    BusinessChannelIntegration,
    InstagramOAuthAttempt,
    WhatsAppEmbeddedSignupAttempt,
)
from app.services.incident_service import report_incident, resolve_related_incidents
from app.services.instagram_provider import (
    InstagramVerificationResult,
    ProviderSendResult,
    send_instagram_text_message,
    verify_instagram_access_token,
)
from app.services.integration_crypto_service import (
    IntegrationCryptoError,
    decrypt_secret,
    encrypt_secret,
    load_encryption_configuration,
)

INSTAGRAM_PROVIDER = "instagram"
INSTAGRAM_CHANNEL = "instagram"
SENDABLE_INTEGRATION_STATUSES = ("connected", "degraded")
EXPIRATION_WARNING_DAYS = 7
logger = logging.getLogger(__name__)


def oauth_failure_status(error_code: str | None, error_subcode: str | None) -> str | None:
    if error_code != "190":
        return None
    return "expired" if error_subcode in {"460", "463"} else "revoked"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def mask_external_account_id(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * min(8, len(value) - 4)}{value[-4:]}"


def get_instagram_integration(
    db: Session,
    *,
    business_id: int,
) -> BusinessChannelIntegration | None:
    return (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.business_id == business_id,
            BusinessChannelIntegration.provider == INSTAGRAM_PROVIDER,
            BusinessChannelIntegration.channel == INSTAGRAM_CHANNEL,
        )
        .first()
    )


def lock_instagram_integration(
    db: Session,
    integration: BusinessChannelIntegration,
) -> BusinessChannelIntegration:
    query = db.query(BusinessChannelIntegration).filter(
        BusinessChannelIntegration.id == integration.id,
        BusinessChannelIntegration.business_id == integration.business_id,
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.populate_existing().with_for_update()
    return query.one()


def integration_expiration_state(
    integration: BusinessChannelIntegration,
    *,
    now: datetime | None = None,
) -> tuple[bool, bool, int | None]:
    expires_at = as_utc(integration.token_expires_at)
    if expires_at is None:
        return False, False, None
    current = now or utc_now()
    seconds = (expires_at - current).total_seconds()
    days_remaining = max(0, int(seconds // 86400))
    return seconds <= 0, 0 < seconds <= EXPIRATION_WARNING_DAYS * 86400, days_remaining


def serialize_instagram_integration(
    integration: BusinessChannelIntegration,
    *,
    include_technical_details: bool = True,
) -> dict:
    expired, expires_soon, days_remaining = integration_expiration_state(integration)
    try:
        scopes = json.loads(integration.granted_scopes_json or "[]")
    except (TypeError, ValueError):
        scopes = []
    payload = {
        "id": integration.id,
        "business_id": integration.business_id,
        "channel": integration.channel,
        "provider": integration.provider,
        "external_account_id_masked": mask_external_account_id(integration.external_account_id),
        "external_account_name": integration.external_account_name,
        "integration_status": "expired" if expired else integration.integration_status,
        "connected_at": integration.connected_at,
        "disconnected_at": integration.disconnected_at,
        "last_verified_at": integration.last_verified_at,
        "last_success_at": integration.last_success_at,
        "token_expires_at": integration.token_expires_at,
        "days_remaining": days_remaining,
        "expires_soon": expires_soon,
        "has_credentials": bool(integration.encrypted_access_token),
        "has_open_incident": False,
    }
    if include_technical_details:
        payload.update(
            provider_status=integration.provider_status,
            granted_scopes=scopes if isinstance(scopes, list) else [],
            last_error_at=integration.last_error_at,
            last_error_code=integration.last_error_code,
            last_error_subcode=integration.last_error_subcode,
            last_error_type=integration.last_error_type,
            safe_error_message=integration.safe_error_message,
            encryption_key_version=integration.encryption_key_version,
        )
    return payload


def serialize_admin_integration_status(
    integration: BusinessChannelIntegration | None,
) -> dict:
    if integration is None or integration.integration_status == "disconnected":
        state = "disconnected"
        message = "Instagram no está conectado."
    elif (
        integration.integration_status == "connected"
        and not integration_expiration_state(integration)[0]
    ):
        state = "connected"
        message = "Instagram conectado."
    else:
        state = "needs_review"
        message = (
            "La conexión con Instagram necesita revisión. El equipo de AutonoGrow "
            "ya ha recibido el aviso."
        )
    return {
        "provider": INSTAGRAM_PROVIDER,
        "state": state,
        "message": message,
        "token_expires_at": integration.token_expires_at if integration else None,
    }


def report_integration_incident(
    db: Session,
    *,
    integration: BusinessChannelIntegration | None,
    category: str,
    severity: str,
    operation: str,
    error_code: str | None = None,
    safe_details: dict | None = None,
    business_id: int | None = None,
) -> None:
    report_incident(
        db,
        category=category,
        severity=severity,
        business_id=integration.business_id if integration else business_id,
        integration_id=integration.id if integration else None,
        channel=INSTAGRAM_CHANNEL,
        provider=INSTAGRAM_PROVIDER,
        provider_error_code=error_code,
        operation=operation,
        safe_details=safe_details,
    )


def evaluate_integration_expiration(
    db: Session,
    integration: BusinessChannelIntegration,
) -> bool:
    expired, _, _ = integration_expiration_state(integration)
    if not expired:
        return False
    if integration.integration_status != "expired":
        old_status = integration.integration_status
        integration.integration_status = "expired"
        integration.provider_status = "token_expired"
        integration.last_error_at = utc_now()
        integration.last_error_code = "integration_expired"
        integration.safe_error_message = "Instagram access token has expired"
        report_integration_incident(
            db,
            integration=integration,
            category="instagram_token_expired",
            severity="high",
            operation="token_expiration",
            error_code="integration_expired",
            safe_details={"integration_status": "expired"},
        )
        record_audit(
            db,
            action="instagram_token_expired",
            business_id=integration.business_id,
            resource_type="business_channel_integration",
            resource_id=integration.id,
            metadata={
                "business_id": integration.business_id,
                "integration_id": integration.id,
                "external_account_id": mask_external_account_id(integration.external_account_id),
                "old_status": old_status,
                "new_status": "expired",
                "safe_code": "integration_expired",
                "timestamp": utc_now().isoformat(),
            },
            commit=False,
        )
    return True


def resolve_instagram_integration_for_event(
    db: Session,
    *,
    sender_id: str,
    recipient_id: str,
    is_echo: bool,
) -> BusinessChannelIntegration | None:
    external_account_id = sender_id if is_echo else recipient_id
    if not external_account_id:
        return None
    return (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.provider == INSTAGRAM_PROVIDER,
            BusinessChannelIntegration.external_account_id == external_account_id,
        )
        .first()
    )


def send_business_instagram_message(
    db: Session,
    *,
    business_id: int,
    recipient_id: str,
    text: str,
    settings: Settings | None = None,
) -> tuple[ProviderSendResult, BusinessChannelIntegration | None]:
    settings = settings or get_settings()
    integration = get_instagram_integration(db, business_id=business_id)
    if integration is None:
        return (
            ProviderSendResult(
                "failed",
                error_message="Instagram integration is not configured",
                error_code="integration_not_configured",
            ),
            None,
        )
    if integration.integration_status not in SENDABLE_INTEGRATION_STATUSES:
        code = {
            "expired": "integration_expired",
            "disconnected": "integration_disconnected",
            "revoked": "integration_revoked",
        }.get(integration.integration_status, "integration_unavailable")
        return ProviderSendResult(
            "failed", error_message="Instagram integration is unavailable", error_code=code
        ), integration
    if evaluate_integration_expiration(db, integration):
        return ProviderSendResult(
            "failed",
            error_message="Instagram integration has expired",
            error_code="integration_expired",
        ), integration
    if not integration.encrypted_access_token or not integration.encryption_key_version:
        return ProviderSendResult(
            "failed",
            error_message="Instagram integration has no credentials",
            error_code="integration_not_configured",
        ), integration
    try:
        access_token = decrypt_secret(
            integration.encrypted_access_token,
            integration.encryption_key_version,
            settings=settings,
        )
    except IntegrationCryptoError:
        integration.integration_status = "error"
        integration.last_error_at = utc_now()
        integration.last_error_code = "integration_decryption_failed"
        integration.safe_error_message = "Integration credentials could not be decrypted"
        report_integration_incident(
            db,
            integration=integration,
            category="integration_decryption_failed",
            severity="high",
            operation="decrypt_credentials",
            error_code="integration_decryption_failed",
            safe_details={"integration_status": "error"},
        )
        return ProviderSendResult(
            "failed",
            error_message="Instagram integration credentials are unavailable",
            error_code="integration_decryption_failed",
        ), integration
    credential_snapshot = (
        integration.encrypted_access_token,
        integration.encryption_key_version,
        integration.token_last_refreshed_at,
    )
    external_account_id = integration.external_account_id
    if db.in_transaction():
        db.commit()
    result = send_instagram_text_message(
        recipient_id,
        text,
        access_token=access_token,
        external_account_id=external_account_id,
        settings=settings,
    )
    integration = lock_instagram_integration(db, integration)
    current_credentials = (
        integration.encrypted_access_token,
        integration.encryption_key_version,
        integration.token_last_refreshed_at,
    )
    if current_credentials != credential_snapshot:
        logger.info("stale_integration_send_result_ignored integration_id=%s", integration.id)
        return result, integration
    now = utc_now()
    if result.ok:
        integration.integration_status = "connected"
        integration.provider_status = "available"
        integration.last_success_at = now
        integration.safe_error_message = None
        integration.last_error_code = None
        integration.last_error_subcode = None
        integration.last_error_type = None
    else:
        old_status = integration.integration_status
        integration.last_error_at = now
        integration.last_error_code = result.error_code
        integration.last_error_subcode = result.error_subcode
        integration.last_error_type = result.error_type
        integration.safe_error_message = result.error_message
        oauth_status = oauth_failure_status(result.error_code, result.error_subcode)
        if oauth_status:
            integration.integration_status = oauth_status
            integration.provider_status = f"oauth_{oauth_status}"
            if old_status != oauth_status:
                record_audit(
                    db,
                    action=f"instagram_token_{oauth_status}",
                    business_id=integration.business_id,
                    resource_type="business_channel_integration",
                    resource_id=integration.id,
                    metadata={
                        "business_id": integration.business_id,
                        "integration_id": integration.id,
                        "external_account_id": mask_external_account_id(
                            integration.external_account_id
                        ),
                        "old_status": old_status,
                        "new_status": oauth_status,
                        "safe_code": "190",
                        "timestamp": now.isoformat(),
                    },
                    commit=False,
                )
        elif result.timed_out:
            integration.integration_status = "degraded"
            integration.provider_status = "temporary_failure"
    return result, integration


def verify_instagram_integration(
    db: Session,
    integration: BusinessChannelIntegration,
    *,
    access_token: str | None = None,
    settings: Settings | None = None,
) -> InstagramVerificationResult:
    settings = settings or get_settings()
    credential_snapshot = (
        integration.encrypted_access_token,
        integration.encryption_key_version,
        integration.token_last_refreshed_at,
    )
    if evaluate_integration_expiration(db, integration):
        return InstagramVerificationResult(
            ok=False,
            account_id=integration.external_account_id,
            error_message="Instagram integration has expired",
            error_code="integration_expired",
        )
    token = access_token
    if token is None:
        if not integration.encrypted_access_token or not integration.encryption_key_version:
            return InstagramVerificationResult(
                ok=False,
                error_message="Integration credentials are unavailable",
                error_code="integration_not_configured",
            )
        try:
            token = decrypt_secret(
                integration.encrypted_access_token,
                integration.encryption_key_version,
                settings=settings,
            )
        except IntegrationCryptoError:
            integration.integration_status = "error"
            integration.last_error_at = utc_now()
            integration.last_error_code = "integration_decryption_failed"
            integration.safe_error_message = "Integration credentials could not be decrypted"
            report_integration_incident(
                db,
                integration=integration,
                category="integration_decryption_failed",
                severity="high",
                operation="verify_integration",
                error_code="integration_decryption_failed",
            )
            return InstagramVerificationResult(
                ok=False,
                error_message="Integration credentials are unavailable",
                error_code="integration_decryption_failed",
            )
    external_account_id = integration.external_account_id
    # Provider I/O must not hold a database transaction or a PostgreSQL row lock.
    if db.in_transaction():
        db.commit()
    result = verify_instagram_access_token(external_account_id, token, settings=settings)
    integration = lock_instagram_integration(db, integration)
    current_credentials = (
        integration.encrypted_access_token,
        integration.encryption_key_version,
        integration.token_last_refreshed_at,
    )
    if current_credentials != credential_snapshot:
        logger.info(
            "stale_integration_verification_ignored integration_id=%s",
            integration.id,
        )
        return result
    now = utc_now()
    old_status = integration.integration_status
    integration.last_verified_at = now
    if result.ok:
        integration.integration_status = "connected"
        integration.provider_status = result.provider_status or "available"
        integration.external_account_name = result.account_name or integration.external_account_name
        integration.granted_scopes_json = json.dumps(list(result.scopes))
        integration.last_success_at = now
        integration.last_error_at = None
        integration.last_error_code = None
        integration.last_error_subcode = None
        integration.last_error_type = None
        integration.safe_error_message = None
        resolve_related_incidents(
            db,
            business_id=integration.business_id,
            integration_id=integration.id,
            channel=INSTAGRAM_CHANNEL,
            provider=INSTAGRAM_PROVIDER,
            operation="verify_integration",
            settings=settings,
        )
    else:
        oauth_status = oauth_failure_status(result.error_code, result.error_subcode)
        integration.integration_status = oauth_status or "degraded"
        integration.provider_status = "verification_failed"
        integration.last_error_at = now
        integration.last_error_code = result.error_code
        integration.last_error_subcode = result.error_subcode
        integration.last_error_type = result.error_type
        integration.safe_error_message = result.error_message
        category = (
            f"instagram_token_{oauth_status}" if oauth_status else "instagram_verification_failed"
        )
        report_integration_incident(
            db,
            integration=integration,
            category=category,
            severity="high" if result.error_code == "190" else "medium",
            operation="verify_integration",
            error_code=result.error_code,
            safe_details={
                "error_type": result.error_type,
                "error_subcode": result.error_subcode,
                "http_status": result.http_status,
                "integration_status": integration.integration_status,
            },
        )
        if oauth_status and old_status != oauth_status:
            record_audit(
                db,
                action=f"instagram_token_{oauth_status}",
                business_id=integration.business_id,
                resource_type="business_channel_integration",
                resource_id=integration.id,
                metadata={
                    "business_id": integration.business_id,
                    "integration_id": integration.id,
                    "external_account_id": mask_external_account_id(
                        integration.external_account_id
                    ),
                    "old_status": old_status,
                    "new_status": oauth_status,
                    "safe_code": "190",
                    "timestamp": now.isoformat(),
                },
                commit=False,
            )
    return result


def replace_integration_credentials(
    integration: BusinessChannelIntegration,
    *,
    access_token: str,
    token_expires_at: datetime | None,
    settings: Settings | None = None,
) -> None:
    ciphertext, version = encrypt_secret(access_token, settings=settings)
    now = utc_now()
    integration.encrypted_access_token = ciphertext
    integration.encryption_key_version = version
    integration.token_expires_at = token_expires_at
    integration.token_last_refreshed_at = now
    integration.disconnected_at = None


def validate_persisted_integration_secrets(
    db: Session,
    *,
    settings: Settings | None = None,
) -> None:
    rows = (
        db.query(BusinessChannelIntegration)
        .filter(BusinessChannelIntegration.encrypted_access_token.is_not(None))
        .all()
    )
    instagram_candidates = (
        db.query(InstagramOAuthAttempt)
        .filter(InstagramOAuthAttempt.candidate_encrypted_access_token.is_not(None))
        .all()
    )
    whatsapp_candidates = (
        db.query(WhatsAppEmbeddedSignupAttempt)
        .filter(WhatsAppEmbeddedSignupAttempt.candidate_encrypted_access_token.is_not(None))
        .all()
    )
    if not rows and not instagram_candidates and not whatsapp_candidates:
        return
    configuration = load_encryption_configuration(settings, required=True)
    for integration in rows:
        version = integration.encryption_key_version
        if not version or version not in configuration.keys:
            raise IntegrationCryptoError(
                "A stored integration uses an unavailable encryption key version"
            )
        decrypt_secret(
            integration.encrypted_access_token or "",
            version,
            settings=settings,
        )
    for candidate in instagram_candidates:
        version = candidate.candidate_encryption_key_version
        if not version or version not in configuration.keys:
            raise IntegrationCryptoError(
                "A stored OAuth candidate uses an unavailable encryption key version"
            )
        decrypt_secret(
            candidate.candidate_encrypted_access_token or "",
            version,
            settings=settings,
        )
    for whatsapp_candidate in whatsapp_candidates:
        version = whatsapp_candidate.candidate_encryption_key_version
        if not version or version not in configuration.keys:
            raise IntegrationCryptoError(
                "A stored WhatsApp candidate uses an unavailable encryption key version"
            )
        decrypt_secret(
            whatsapp_candidate.candidate_encrypted_access_token or "",
            version,
            settings=settings,
        )


def migrate_global_instagram_integration(
    db: Session,
    *,
    settings: Settings | None = None,
) -> BusinessChannelIntegration | None:
    settings = settings or get_settings()
    token = settings.instagram_access_token.strip()
    account_id = settings.instagram_business_account_id.strip()
    business_slug = settings.instagram_default_business_slug.strip()
    if not any((token, account_id, business_slug)):
        return None
    if not all((token, account_id, business_slug)):
        raise IntegrationCryptoError("Legacy Instagram migration configuration is incomplete")
    business = db.query(Business).filter(Business.slug == business_slug).first()
    if business is None:
        raise IntegrationCryptoError("Legacy Instagram migration business was not found")
    existing = (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.provider == INSTAGRAM_PROVIDER,
            BusinessChannelIntegration.external_account_id == account_id,
        )
        .first()
    )
    if existing is not None:
        if existing.business_id != business.id:
            raise IntegrationCryptoError(
                "Legacy Instagram account already belongs to another business"
            )
        logger.warning(
            "Deprecated global Instagram configuration detected; database integration already exists"
        )
        return existing
    ciphertext, version = encrypt_secret(token, settings=settings)
    now = utc_now()
    integration = BusinessChannelIntegration(
        business_id=business.id,
        channel=INSTAGRAM_CHANNEL,
        provider=INSTAGRAM_PROVIDER,
        external_account_id=account_id,
        encrypted_access_token=ciphertext,
        encryption_key_version=version,
        token_type="bearer",
        token_last_refreshed_at=now,
        integration_status="pending",
        provider_status="legacy_migration_pending_verification",
        created_at=now,
        updated_at=now,
    )
    db.add(integration)
    db.flush()
    record_audit(
        db,
        action="instagram_global_integration_migrated",
        business_id=business.id,
        resource_type="business_channel_integration",
        resource_id=integration.id,
        metadata={
            "business_id": business.id,
            "integration_id": integration.id,
            "external_account_id": mask_external_account_id(account_id),
            "old_status": None,
            "new_status": "pending",
            "timestamp": now.isoformat(),
        },
        commit=False,
    )
    logger.warning(
        "Deprecated global Instagram configuration migrated to an encrypted database integration"
    )
    return integration


def initialize_instagram_integrations(
    db: Session,
    *,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    if settings.instagram_provider_enabled:
        load_encryption_configuration(settings, required=True)
    validate_persisted_integration_secrets(db, settings=settings)
    migrated = migrate_global_instagram_integration(db, settings=settings)
    if migrated is not None:
        db.commit()
    validate_persisted_integration_secrets(db, settings=settings)


def reencrypt_integration_secret(
    integration: BusinessChannelIntegration,
    *,
    settings: Settings | None = None,
) -> None:
    if not integration.encrypted_access_token or not integration.encryption_key_version:
        return
    plaintext = decrypt_secret(
        integration.encrypted_access_token,
        integration.encryption_key_version,
        settings=settings,
    )
    ciphertext, version = encrypt_secret(plaintext, settings=settings)
    integration.encrypted_access_token = ciphertext
    integration.encryption_key_version = version
    integration.updated_at = utc_now()
