from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from app.core.config import Settings, get_settings

INSTAGRAM_LOGIN_SCOPES = (
    "instagram_business_basic",
    "instagram_business_manage_messages",
)
INSTAGRAM_WEBHOOK_FIELDS = ("messages",)
INSTAGRAM_PROFESSIONAL_ACCOUNT_TYPES = {"BUSINESS", "CREATOR"}


class InstagramLoginProviderError(RuntimeError):
    def __init__(self, safe_code: str, safe_message: str):
        super().__init__(safe_message)
        self.safe_code = safe_code
        self.safe_message = safe_message


@dataclass(frozen=True)
class InstagramTokenResult:
    access_token: str
    expires_at: datetime | None
    token_type: str
    granted_scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class InstagramAccountProfile:
    external_account_id: str
    scoped_account_id: str
    account_name: str | None
    account_type: str


def _version(settings: Settings) -> str:
    version = settings.instagram_login_graph_api_version.strip()
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise InstagramLoginProviderError("configuration_invalid", "Instagram Login is unavailable")
    return version


def _response_status_code(response: object) -> int:
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return 200 if getattr(response, "ok", False) else 400


def build_instagram_authorization_url(state: str, *, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    query = urlencode(
        {
            "client_id": settings.instagram_login_client_id.strip(),
            "redirect_uri": settings.instagram_login_redirect_uri.strip(),
            "response_type": "code",
            "scope": ",".join(INSTAGRAM_LOGIN_SCOPES),
            "state": state,
        }
    )
    return f"https://www.instagram.com/oauth/authorize?{query}"


def exchange_instagram_authorization_code(
    code: str,
    *,
    settings: Settings | None = None,
    timeout_seconds: float = 10.0,
) -> InstagramTokenResult:
    settings = settings or get_settings()
    try:
        response = requests.post(
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": settings.instagram_login_client_id.strip(),
                "client_secret": settings.instagram_login_client_secret,
                "grant_type": "authorization_code",
                "redirect_uri": settings.instagram_login_redirect_uri.strip(),
                "code": code,
            },
            timeout=timeout_seconds,
        )
    except requests.Timeout as exc:
        raise InstagramLoginProviderError(
            "token_exchange_timeout", "Instagram did not respond"
        ) from exc
    except requests.RequestException as exc:
        raise InstagramLoginProviderError(
            "token_exchange_failed", "Instagram authorization failed"
        ) from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    token = payload.get("access_token") if isinstance(payload, dict) else None
    raw_permissions = payload.get("permissions") if isinstance(payload, dict) else None
    if not response.ok or not isinstance(token, str) or not token.strip():
        raise InstagramLoginProviderError(
            "token_exchange_rejected", "Instagram authorization was rejected"
        )
    if isinstance(raw_permissions, str):
        permissions = {item.strip() for item in raw_permissions.split(",") if item.strip()}
    elif isinstance(raw_permissions, list):
        permissions = {str(item).strip() for item in raw_permissions if str(item).strip()}
    else:
        permissions = set()
    if not set(INSTAGRAM_LOGIN_SCOPES).issubset(permissions):
        raise InstagramLoginProviderError(
            "permissions_incomplete",
            "Not all required Instagram permissions were granted",
        )
    granted = tuple(scope for scope in INSTAGRAM_LOGIN_SCOPES if scope in permissions)
    return InstagramTokenResult(
        access_token=token.strip(),
        expires_at=None,
        token_type="bearer",
        granted_scopes=granted,
    )


def exchange_instagram_long_lived_token(
    short_lived_token: str,
    *,
    granted_scopes: tuple[str, ...] = (),
    settings: Settings | None = None,
    timeout_seconds: float = 10.0,
) -> InstagramTokenResult:
    settings = settings or get_settings()
    try:
        response = requests.get(
            "https://graph.instagram.com/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": settings.instagram_login_client_secret,
                "access_token": short_lived_token,
            },
            timeout=timeout_seconds,
        )
    except requests.Timeout as exc:
        raise InstagramLoginProviderError(
            "long_lived_token_timeout", "Instagram did not respond"
        ) from exc
    except requests.RequestException as exc:
        raise InstagramLoginProviderError(
            "long_lived_token_failed", "Instagram token exchange failed"
        ) from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    token = payload.get("access_token") if isinstance(payload, dict) else None
    expires_in = payload.get("expires_in") if isinstance(payload, dict) else None
    if not response.ok or not isinstance(token, str) or not token.strip():
        raise InstagramLoginProviderError(
            "long_lived_token_rejected", "Instagram token exchange was rejected"
        )
    expires_at = None
    if isinstance(expires_in, (int, float)) and 0 < expires_in <= 366 * 24 * 60 * 60:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    return InstagramTokenResult(
        access_token=token.strip(),
        expires_at=expires_at,
        token_type=str(payload.get("token_type") or "bearer")[:40],
        granted_scopes=granted_scopes,
    )


def get_instagram_account_profile(
    access_token: str,
    *,
    settings: Settings | None = None,
    timeout_seconds: float = 10.0,
) -> InstagramAccountProfile:
    settings = settings or get_settings()
    try:
        response = requests.get(
            f"https://graph.instagram.com/{_version(settings)}/me",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"fields": "id,user_id,username,name,account_type"},
            timeout=timeout_seconds,
        )
    except requests.Timeout as exc:
        raise InstagramLoginProviderError("profile_timeout", "Instagram did not respond") from exc
    except requests.RequestException as exc:
        raise InstagramLoginProviderError(
            "profile_failed", "Instagram account validation failed"
        ) from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    scoped_id = str(payload.get("id") or "").strip() if isinstance(payload, dict) else ""
    routing_id = (
        str(payload.get("user_id") or scoped_id).strip() if isinstance(payload, dict) else ""
    )
    account_type = (
        str(payload.get("account_type") or "").strip().upper() if isinstance(payload, dict) else ""
    )
    status_code = _response_status_code(response)
    if status_code == 429 or status_code >= 500:
        raise InstagramLoginProviderError(
            "profile_failed", "Instagram account validation is temporarily unavailable"
        )
    if not response.ok or not scoped_id or not routing_id:
        raise InstagramLoginProviderError("profile_rejected", "Instagram account validation failed")
    if account_type not in INSTAGRAM_PROFESSIONAL_ACCOUNT_TYPES:
        raise InstagramLoginProviderError(
            "professional_account_required",
            "A professional Instagram Business or Creator account is required",
        )
    account_name = payload.get("username") or payload.get("name")
    return InstagramAccountProfile(
        external_account_id=routing_id[:255],
        scoped_account_id=scoped_id[:255],
        account_name=str(account_name)[:255] if account_name else None,
        account_type=account_type,
    )


def subscribe_instagram_messages_webhook(
    external_account_id: str,
    access_token: str,
    *,
    settings: Settings | None = None,
    timeout_seconds: float = 10.0,
) -> None:
    settings = settings or get_settings()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", external_account_id):
        raise InstagramLoginProviderError(
            "account_id_invalid", "Instagram account validation failed"
        )
    try:
        response = requests.post(
            f"https://graph.instagram.com/{_version(settings)}/{external_account_id}/subscribed_apps",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"subscribed_fields": ",".join(INSTAGRAM_WEBHOOK_FIELDS)},
            timeout=timeout_seconds,
        )
    except requests.Timeout as exc:
        raise InstagramLoginProviderError(
            "webhook_subscription_timeout", "Instagram did not respond"
        ) from exc
    except requests.RequestException as exc:
        raise InstagramLoginProviderError(
            "webhook_subscription_failed", "Instagram webhook setup failed"
        ) from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    status_code = _response_status_code(response)
    if status_code == 429 or status_code >= 500:
        raise InstagramLoginProviderError(
            "webhook_subscription_failed", "Instagram webhook setup is temporarily unavailable"
        )
    if not response.ok or not isinstance(payload, dict) or payload.get("success") is not True:
        raise InstagramLoginProviderError(
            "webhook_subscription_rejected", "Instagram webhook setup failed"
        )


def instagram_messages_subscription_active(
    external_account_id: str,
    access_token: str,
    *,
    settings: Settings | None = None,
    timeout_seconds: float = 10.0,
) -> bool:
    """Return whether this app is subscribed to the messages field.

    Only the bounded subscription fields are interpreted; the provider response
    is never returned to callers or persisted.
    """
    settings = settings or get_settings()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", external_account_id):
        raise InstagramLoginProviderError(
            "account_id_invalid", "Instagram account validation failed"
        )
    try:
        response = requests.get(
            f"https://graph.instagram.com/{_version(settings)}/{external_account_id}/subscribed_apps",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout_seconds,
        )
    except requests.Timeout as exc:
        raise InstagramLoginProviderError(
            "webhook_inspection_timeout", "Instagram did not respond"
        ) from exc
    except requests.RequestException as exc:
        raise InstagramLoginProviderError(
            "webhook_inspection_failed", "Instagram webhook status could not be checked"
        ) from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    data = payload.get("data") if isinstance(payload, dict) else None
    status_code = _response_status_code(response)
    if status_code == 429 or status_code >= 500:
        raise InstagramLoginProviderError(
            "webhook_inspection_failed",
            "Instagram webhook status is temporarily unavailable",
        )
    if not response.ok or not isinstance(data, list):
        raise InstagramLoginProviderError(
            "webhook_inspection_rejected", "Instagram webhook status could not be checked"
        )
    expected_app_id = settings.instagram_login_client_id.strip()
    for item in data:
        if not isinstance(item, dict):
            continue
        if expected_app_id and str(item.get("id") or "") != expected_app_id:
            continue
        fields = item.get("subscribed_fields")
        if isinstance(fields, list) and "messages" in fields:
            return True
    return False
