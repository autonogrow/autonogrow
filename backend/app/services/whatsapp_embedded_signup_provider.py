from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

import requests

from app.core.config import Settings, get_settings

WHATSAPP_EMBEDDED_SIGNUP_EVENT_TYPE = "WA_EMBEDDED_SIGNUP"
WHATSAPP_EMBEDDED_SIGNUP_FINISH_EVENT = "FINISH"
WHATSAPP_EMBEDDED_SIGNUP_SDK_URL = "https://connect.facebook.net/en_US/sdk.js"
WHATSAPP_EMBEDDED_SIGNUP_SCOPES = (
    "business_management",
    "whatsapp_business_management",
    "whatsapp_business_messaging",
)
META_ID_PATTERN = re.compile(r"[1-9][0-9]{5,39}")


class WhatsAppEmbeddedSignupProviderError(RuntimeError):
    def __init__(self, safe_code: str, safe_message: str):
        super().__init__(safe_message)
        self.safe_code = safe_code
        self.safe_message = safe_message


@dataclass(frozen=True)
class WhatsAppBusinessToken:
    access_token: str
    token_type: str
    expires_at: datetime | None
    granted_scopes: tuple[str, ...]


@dataclass(frozen=True)
class WhatsAppVerifiedAssets:
    meta_business_id: str
    waba_id: str
    phone_number_id: str
    verified_name: str | None
    display_phone_number: str
    phone_status: str
    registration_status: str


def _version(settings: Settings) -> str:
    version = settings.whatsapp_embedded_signup_graph_api_version.strip()
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise WhatsAppEmbeddedSignupProviderError(
            "configuration_invalid", "WhatsApp Embedded Signup is unavailable"
        )
    return version


def _payload(response: requests.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _provider_request_error(prefix: str, exc: requests.RequestException) -> None:
    if isinstance(exc, requests.Timeout):
        raise WhatsAppEmbeddedSignupProviderError(
            f"{prefix}_timeout", "Meta did not respond"
        ) from exc
    raise WhatsAppEmbeddedSignupProviderError(
        f"{prefix}_failed", "Meta could not complete WhatsApp setup"
    ) from exc


def _require_meta_id(value: str, *, safe_code: str) -> str:
    normalized = str(value or "").strip()
    if META_ID_PATTERN.fullmatch(normalized) is None:
        raise WhatsAppEmbeddedSignupProviderError(
            safe_code, "Meta returned inconsistent WhatsApp assets"
        )
    return normalized


def exchange_whatsapp_embedded_signup_code(
    code: str,
    *,
    settings: Settings | None = None,
    timeout_seconds: float = 10.0,
) -> str:
    settings = settings or get_settings()
    try:
        response = requests.get(
            f"https://graph.facebook.com/{_version(settings)}/oauth/access_token",
            params={
                "client_id": settings.meta_app_id.strip(),
                "client_secret": settings.meta_app_secret,
                "code": code,
            },
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        _provider_request_error("token_exchange", exc)
    payload = _payload(response)
    token = payload.get("access_token")
    if not response.ok or not isinstance(token, str) or not token.strip():
        raise WhatsAppEmbeddedSignupProviderError(
            "token_exchange_rejected", "Meta rejected WhatsApp authorization"
        )
    return token.strip()


def inspect_whatsapp_business_token(
    access_token: str,
    *,
    expected_waba_id: str,
    settings: Settings | None = None,
    timeout_seconds: float = 10.0,
) -> WhatsAppBusinessToken:
    settings = settings or get_settings()
    expected_waba_id = _require_meta_id(expected_waba_id, safe_code="waba_id_invalid")
    app_access_token = f"{settings.meta_app_id.strip()}|{settings.meta_app_secret}"
    try:
        response = requests.get(
            f"https://graph.facebook.com/{_version(settings)}/debug_token",
            headers={"Authorization": f"Bearer {app_access_token}"},
            params={"input_token": access_token},
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        _provider_request_error("token_inspection", exc)
    payload = _payload(response)
    raw_data = payload.get("data")
    data = cast(dict[str, Any], raw_data) if isinstance(raw_data, dict) else {}
    scopes = {str(item) for item in data.get("scopes", []) if isinstance(item, str)}
    missing = set(WHATSAPP_EMBEDDED_SIGNUP_SCOPES) - scopes
    if (
        not response.ok
        or data.get("is_valid") is not True
        or str(data.get("app_id") or "") != settings.meta_app_id.strip()
    ):
        raise WhatsAppEmbeddedSignupProviderError(
            "token_invalid", "Meta returned an invalid WhatsApp authorization"
        )
    if missing:
        raise WhatsAppEmbeddedSignupProviderError(
            "permissions_incomplete", "Not all required WhatsApp permissions were granted"
        )
    granular_targets: set[str] = set()
    for item in data.get("granular_scopes", []):
        if not isinstance(item, dict):
            continue
        if item.get("scope") in {
            "whatsapp_business_management",
            "whatsapp_business_messaging",
        }:
            granular_targets.update(
                str(target) for target in item.get("target_ids", []) if str(target).strip()
            )
    if granular_targets and expected_waba_id not in granular_targets:
        raise WhatsAppEmbeddedSignupProviderError(
            "waba_not_authorized", "The WhatsApp Business Account was not authorized"
        )
    expires_at = None
    raw_expiry = data.get("expires_at")
    if isinstance(raw_expiry, (int, float)) and raw_expiry > 0:
        expires_at = datetime.fromtimestamp(int(raw_expiry), tz=timezone.utc)
    return WhatsAppBusinessToken(
        access_token=access_token,
        token_type=str(data.get("type") or "business_integration_system_user")[:40].lower(),
        expires_at=expires_at,
        granted_scopes=tuple(scope for scope in WHATSAPP_EMBEDDED_SIGNUP_SCOPES if scope in scopes),
    )


def _business_waba_ids(
    meta_business_id: str,
    access_token: str,
    *,
    settings: Settings,
    timeout_seconds: float,
) -> set[str]:
    found: set[str] = set()
    for edge in ("owned_whatsapp_business_accounts", "client_whatsapp_business_accounts"):
        try:
            response = requests.get(
                f"https://graph.facebook.com/{_version(settings)}/{meta_business_id}/{edge}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "id,name", "limit": "100"},
                timeout=timeout_seconds,
            )
        except requests.RequestException as exc:
            _provider_request_error("business_verification", exc)
        if response.status_code in {400, 403, 404}:
            continue
        payload = _payload(response)
        if not response.ok or not isinstance(payload.get("data"), list):
            raise WhatsAppEmbeddedSignupProviderError(
                "business_verification_rejected", "Meta Business could not be verified"
            )
        found.update(
            str(item.get("id"))
            for item in payload["data"]
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        )
    return found


def verify_whatsapp_embedded_signup_assets(
    access_token: str,
    *,
    meta_business_id: str,
    waba_id: str,
    phone_number_id: str,
    settings: Settings | None = None,
    timeout_seconds: float = 10.0,
) -> WhatsAppVerifiedAssets:
    settings = settings or get_settings()
    meta_business_id = _require_meta_id(meta_business_id, safe_code="business_id_invalid")
    waba_id = _require_meta_id(waba_id, safe_code="waba_id_invalid")
    phone_number_id = _require_meta_id(phone_number_id, safe_code="phone_number_id_invalid")
    if waba_id not in _business_waba_ids(
        meta_business_id,
        access_token,
        settings=settings,
        timeout_seconds=timeout_seconds,
    ):
        raise WhatsAppEmbeddedSignupProviderError(
            "waba_business_mismatch", "The WhatsApp Business Account could not be verified"
        )
    try:
        response = requests.get(
            f"https://graph.facebook.com/{_version(settings)}/{waba_id}/phone_numbers",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "fields": (
                    "id,verified_name,display_phone_number,quality_rating,"
                    "code_verification_status,platform_type,is_on_biz_app"
                ),
                "limit": "100",
            },
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        _provider_request_error("phone_verification", exc)
    payload = _payload(response)
    raw_items = payload.get("data")
    items = raw_items if isinstance(raw_items, list) else []
    phone: dict[str, Any] | None = None
    for item in items:
        if isinstance(item, dict) and str(item.get("id") or "") == phone_number_id:
            phone = item
            break
    if not response.ok or phone is None:
        raise WhatsAppEmbeddedSignupProviderError(
            "phone_waba_mismatch", "The WhatsApp phone number could not be verified"
        )
    quality = str(phone.get("quality_rating") or "UNKNOWN").upper()[:40]
    verification = str(phone.get("code_verification_status") or "UNKNOWN").upper()[:40]
    platform = str(phone.get("platform_type") or "UNKNOWN").upper()[:40]
    if quality in {"BLOCKED", "FLAGGED", "RESTRICTED", "RED"}:
        raise WhatsAppEmbeddedSignupProviderError(
            "phone_not_operational", "The WhatsApp phone number is not operational"
        )
    registration_status = (
        "registered"
        if platform in {"CLOUD_API", "CLOUD_API_AND_WHATSAPP_BUSINESS_APP"}
        and verification == "VERIFIED"
        else "registration_required"
    )
    display = str(phone.get("display_phone_number") or "").strip()
    return WhatsAppVerifiedAssets(
        meta_business_id=meta_business_id,
        waba_id=waba_id,
        phone_number_id=phone_number_id,
        verified_name=(
            str(phone.get("verified_name"))[:255] if phone.get("verified_name") else None
        ),
        display_phone_number=display,
        phone_status=f"{quality}:{verification}:{platform}"[:80],
        registration_status=registration_status,
    )


def subscribe_app_to_whatsapp_waba(
    waba_id: str,
    access_token: str,
    *,
    settings: Settings | None = None,
    timeout_seconds: float = 10.0,
) -> None:
    settings = settings or get_settings()
    waba_id = _require_meta_id(waba_id, safe_code="waba_id_invalid")
    try:
        response = requests.post(
            f"https://graph.facebook.com/{_version(settings)}/{waba_id}/subscribed_apps",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        _provider_request_error("app_subscription", exc)
    payload = _payload(response)
    if not response.ok or payload.get("success") is not True:
        raise WhatsAppEmbeddedSignupProviderError(
            "app_subscription_rejected", "Meta did not confirm the WhatsApp subscription"
        )


def redact_display_phone_number(value: str) -> str | None:
    digits = "".join(character for character in value if character.isdigit())
    if not digits:
        return None
    return f"•••• {digits[-4:]}"
