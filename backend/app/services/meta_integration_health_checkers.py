from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.models import BusinessChannelIntegration
from app.services.instagram_login_provider import (
    INSTAGRAM_LOGIN_SCOPES,
    InstagramLoginProviderError,
    get_instagram_account_profile,
    instagram_messages_subscription_active,
    subscribe_instagram_messages_webhook,
)
from app.services.meta_integration_health_contracts import (
    IntegrationHealthChecker,
    IntegrationHealthResult,
    UnsupportedIntegrationHealthProvider,
)
from app.services.whatsapp_embedded_signup_provider import (
    WhatsAppEmbeddedSignupProviderError,
    inspect_whatsapp_business_token,
    subscribe_app_to_whatsapp_waba,
    verify_whatsapp_embedded_signup_assets,
    whatsapp_app_subscription_active,
)

EXPIRY_UNKNOWN = "unknown"
EXPIRY_EXPIRED = "expired"


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _expiry_status(expires_at: datetime | None, *, now: datetime, settings: Settings) -> str:
    expiry = _utc(expires_at)
    if expiry is None:
        return "unknown"
    remaining = expiry - now
    if remaining.total_seconds() <= 0:
        return "expired"
    if remaining <= timedelta(days=settings.meta_token_expiry_critical_days):
        return "critical"
    if remaining <= timedelta(days=settings.meta_token_expiry_warning_days):
        return "expires_soon"
    return "valid"


def _result(
    settings: Settings,
    *,
    status: str,
    token: str,
    subscription: str,
    asset: str,
    code: str | None = None,
    message: str | None = None,
    retryable: bool = False,
    blocking: bool = False,
    reconnect: bool = False,
    metadata: dict[str, str | int | float | bool | None] | None = None,
    now: datetime | None = None,
) -> IntegrationHealthResult:
    checked = now or datetime.now(timezone.utc)
    delay = timedelta(
        hours=1 if retryable else settings.meta_integration_health_check_interval_hours
    )
    return IntegrationHealthResult(
        health_status=status,
        healthy=status == "healthy",
        retryable=retryable,
        blocking=blocking,
        reconnection_required=reconnect,
        safe_error_code=code,
        safe_error_message=message,
        token_expiry_status=token,
        subscription_status=subscription,
        asset_status=asset,
        checked_at=checked,
        next_check_at=checked + delay,
        metadata=dict(metadata or {}),
    )


def _stored_scopes(integration: BusinessChannelIntegration) -> set[str]:
    try:
        parsed = json.loads(integration.granted_scopes_json or "[]")
    except (TypeError, ValueError):
        return set()
    return {str(item) for item in parsed} if isinstance(parsed, list) else set()


def _instagram_failure(
    exc: InstagramLoginProviderError, *, expiry: str, settings: Settings
) -> IntegrationHealthResult:
    if exc.safe_code.endswith(("_timeout", "_failed")):
        return _result(
            settings,
            status="warning",
            token=expiry,
            subscription="unknown",
            asset="unknown",
            code=exc.safe_code,
            message="No pudimos comprobar temporalmente la conexión con Instagram.",
            retryable=True,
        )
    if exc.safe_code in {"profile_rejected", "token_invalid"}:
        return _result(
            settings,
            status="revoked",
            token=EXPIRY_UNKNOWN,
            subscription="unknown",
            asset="inaccessible",
            code="instagram_authorization_revoked",
            message="La autorización de Instagram ya no es válida.",
            blocking=True,
            reconnect=True,
        )
    return _result(
        settings,
        status="action_required",
        token=expiry,
        subscription="unknown",
        asset="invalid",
        code=exc.safe_code,
        message=exc.safe_message,
        blocking=True,
        reconnect=True,
    )


def check_instagram_integration_health(
    integration: BusinessChannelIntegration,
    *,
    access_token: str,
    settings: Settings,
    repair_subscription: bool = False,
) -> IntegrationHealthResult:
    now = datetime.now(timezone.utc)
    expiry = _expiry_status(integration.token_expires_at, now=now, settings=settings)
    if expiry == "expired":
        return _result(
            settings,
            status="action_required",
            token=expiry,
            subscription="unknown",
            asset="unknown",
            code="instagram_token_expired",
            message="La autorización de Instagram ha caducado.",
            blocking=True,
            reconnect=True,
            now=now,
        )
    if not set(INSTAGRAM_LOGIN_SCOPES).issubset(_stored_scopes(integration)):
        return _result(
            settings,
            status="action_required",
            token=expiry,
            subscription="unknown",
            asset="unknown",
            code="instagram_permissions_missing",
            message="Meta retiró uno de los permisos necesarios de Instagram.",
            blocking=True,
            reconnect=True,
            now=now,
        )
    try:
        profile = get_instagram_account_profile(
            access_token,
            settings=settings,
            timeout_seconds=settings.meta_integration_health_job_timeout_seconds,
        )
        if profile.external_account_id != integration.external_account_id:
            return _result(
                settings,
                status="error",
                token=expiry,
                subscription="unknown",
                asset="mismatch",
                code="instagram_account_mismatch",
                message="La cuenta devuelta por Meta no coincide con la integración.",
                blocking=True,
                reconnect=True,
                now=now,
            )
        subscribed = instagram_messages_subscription_active(
            integration.external_account_id,
            access_token,
            settings=settings,
            timeout_seconds=settings.meta_integration_health_job_timeout_seconds,
        )
        if not subscribed and repair_subscription:
            subscribe_instagram_messages_webhook(
                integration.external_account_id,
                access_token,
                settings=settings,
                timeout_seconds=settings.meta_integration_health_job_timeout_seconds,
            )
            subscribed = instagram_messages_subscription_active(
                integration.external_account_id,
                access_token,
                settings=settings,
                timeout_seconds=settings.meta_integration_health_job_timeout_seconds,
            )
    except InstagramLoginProviderError as exc:
        return _instagram_failure(exc, expiry=expiry, settings=settings)
    if not subscribed:
        return _result(
            settings,
            status="degraded",
            token=expiry,
            subscription="missing",
            asset="active",
            code="instagram_subscription_missing",
            message="La suscripción de mensajes de Instagram necesita repararse.",
            retryable=True,
            metadata={"account_type": profile.account_type},
            now=now,
        )
    if expiry in {"critical", "expires_soon"}:
        return _result(
            settings,
            status="action_required" if expiry == "critical" else "warning",
            token=expiry,
            subscription="active",
            asset="active",
            code="instagram_token_expiry_warning",
            message="La autorización de Instagram necesita renovarse pronto.",
            reconnect=expiry == "critical",
            metadata={"account_type": profile.account_type},
            now=now,
        )
    return _result(
        settings,
        status="healthy",
        token=expiry,
        subscription="active",
        asset="active",
        metadata={"account_type": profile.account_type},
        now=now,
    )


def _whatsapp_failure(
    exc: WhatsAppEmbeddedSignupProviderError, *, expiry: str, settings: Settings
) -> IntegrationHealthResult:
    code = exc.safe_code
    if code.endswith(("_timeout", "_failed")):
        return _result(
            settings,
            status="warning",
            token=expiry,
            subscription="unknown",
            asset="unknown",
            code=code,
            message="No pudimos comprobar temporalmente la conexión con WhatsApp.",
            retryable=True,
        )
    if code in {"token_invalid", "token_inspection_rejected"}:
        return _result(
            settings,
            status="revoked",
            token=EXPIRY_UNKNOWN,
            subscription="unknown",
            asset="inaccessible",
            code="whatsapp_authorization_revoked",
            message="La autorización de WhatsApp ya no es válida.",
            blocking=True,
            reconnect=True,
        )
    if code == "phone_not_operational":
        return _result(
            settings,
            status="suspended",
            token=expiry,
            subscription="unknown",
            asset="suspended",
            code=code,
            message="El número está suspendido o restringido en Meta.",
            blocking=True,
            reconnect=True,
        )
    return _result(
        settings,
        status="action_required" if code == "permissions_incomplete" else "error",
        token=expiry,
        subscription="unknown",
        asset="mismatch" if "mismatch" in code else "invalid",
        code=code,
        message=exc.safe_message,
        blocking=True,
        reconnect=True,
    )


def check_whatsapp_integration_health(
    integration: BusinessChannelIntegration,
    *,
    access_token: str,
    settings: Settings,
    repair_subscription: bool = False,
) -> IntegrationHealthResult:
    now = datetime.now(timezone.utc)
    stored_expiry = _expiry_status(integration.token_expires_at, now=now, settings=settings)
    try:
        metadata = json.loads(integration.metadata_json or "{}")
    except (TypeError, ValueError):
        metadata = {}
    meta_business_id = (
        str(metadata.get("meta_business_id") or "") if isinstance(metadata, dict) else ""
    )
    waba_id = str(integration.provider_account_id or "")
    if not meta_business_id or not waba_id:
        return _result(
            settings,
            status="action_required",
            token=stored_expiry,
            subscription="unknown",
            asset="incomplete",
            code="whatsapp_assets_incomplete",
            message="La configuración de WhatsApp está incompleta.",
            blocking=True,
            reconnect=True,
            now=now,
        )
    try:
        inspected = inspect_whatsapp_business_token(
            access_token,
            expected_waba_id=waba_id,
            settings=settings,
            timeout_seconds=settings.meta_integration_health_job_timeout_seconds,
        )
        expiry = _expiry_status(
            inspected.expires_at or integration.token_expires_at, now=now, settings=settings
        )
        if expiry == "expired":
            return _result(
                settings,
                status="revoked",
                token=EXPIRY_EXPIRED,
                subscription="unknown",
                asset="unknown",
                code="whatsapp_token_expired",
                message="La autorización de WhatsApp ha caducado.",
                blocking=True,
                reconnect=True,
                now=now,
            )
        assets = verify_whatsapp_embedded_signup_assets(
            access_token,
            meta_business_id=meta_business_id,
            waba_id=waba_id,
            phone_number_id=integration.external_account_id,
            settings=settings,
            timeout_seconds=settings.meta_integration_health_job_timeout_seconds,
        )
        subscribed = whatsapp_app_subscription_active(
            waba_id,
            access_token,
            settings=settings,
            timeout_seconds=settings.meta_integration_health_job_timeout_seconds,
        )
        if not subscribed and repair_subscription:
            subscribe_app_to_whatsapp_waba(
                waba_id,
                access_token,
                settings=settings,
                timeout_seconds=settings.meta_integration_health_job_timeout_seconds,
            )
            subscribed = whatsapp_app_subscription_active(
                waba_id,
                access_token,
                settings=settings,
                timeout_seconds=settings.meta_integration_health_job_timeout_seconds,
            )
    except WhatsAppEmbeddedSignupProviderError as exc:
        return _whatsapp_failure(exc, expiry=stored_expiry, settings=settings)
    if assets.registration_status != "registered":
        return _result(
            settings,
            status="action_required",
            token=expiry,
            subscription="active" if subscribed else "missing",
            asset="registration_required",
            code="whatsapp_registration_required",
            message="El número de WhatsApp requiere completar su registro en Meta.",
            blocking=True,
            reconnect=True,
            metadata={"phone_status": assets.phone_status},
            now=now,
        )
    if not subscribed:
        return _result(
            settings,
            status="degraded",
            token=expiry,
            subscription="missing",
            asset="active",
            code="whatsapp_subscription_missing",
            message="La suscripción de WhatsApp necesita repararse.",
            retryable=True,
            metadata={"phone_status": assets.phone_status},
            now=now,
        )
    if expiry in {"critical", "expires_soon"}:
        return _result(
            settings,
            status="action_required" if expiry == "critical" else "warning",
            token=expiry,
            subscription="active",
            asset="active",
            code="whatsapp_token_expiry_warning",
            message="La autorización de WhatsApp necesita renovarse pronto.",
            reconnect=expiry == "critical",
            metadata={"phone_status": assets.phone_status},
            now=now,
        )
    return _result(
        settings,
        status="healthy",
        token=expiry,
        subscription="active",
        asset="active",
        metadata={"phone_status": assets.phone_status},
        now=now,
    )


INTEGRATION_HEALTH_CHECKERS: dict[str, IntegrationHealthChecker] = {
    "instagram": check_instagram_integration_health,
    "whatsapp": check_whatsapp_integration_health,
}


def health_checker_for_provider(provider: str) -> IntegrationHealthChecker:
    checker = INTEGRATION_HEALTH_CHECKERS.get(provider)
    if checker is None:
        raise UnsupportedIntegrationHealthProvider("Integration provider is not supported")
    return checker
