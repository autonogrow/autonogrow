from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.core.config import Settings, get_uploads_dir
from app.models import (
    InstagramContent,
    InstagramContentValidation,
    InstagramContentVersion,
    InstagramContentVersionAsset,
    InstagramFinalAsset,
)


class SignedAssetURLInvalid(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedSignedAsset:
    path: Path
    media_type: str
    size_bytes: int


def resolve_private_asset_path(storage_key: str, *, root: Path | None = None) -> Path:
    root = (root or get_uploads_dir()).resolve()
    candidate = (root / storage_key).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SignedAssetURLInvalid("Asset path is invalid") from exc
    return candidate


def _message(business_id: int, version_id: int, asset_id: int, expires: int) -> bytes:
    return f"v1:{business_id}:{version_id}:{asset_id}:{expires}".encode("ascii")


def _signature(
    settings: Settings, business_id: int, version_id: int, asset_id: int, expires: int
) -> str:
    return hmac.new(
        settings.instagram_asset_url_secret.encode("utf-8"),
        _message(business_id, version_id, asset_id, expires),
        hashlib.sha256,
    ).hexdigest()


def build_signed_asset_url(
    settings: Settings,
    *,
    business_id: int,
    version_id: int,
    asset_id: int,
    now: int | None = None,
) -> str:
    if not settings.instagram_asset_url_base or len(settings.instagram_asset_url_secret) < 32:
        raise SignedAssetURLInvalid("Signed asset delivery is not configured")
    expires = (
        now if now is not None else int(time.time())
    ) + settings.instagram_asset_url_ttl_seconds
    signature = _signature(settings, business_id, version_id, asset_id, expires)
    query = urlencode({"expires": expires, "signature": signature})
    return (
        f"{settings.instagram_asset_url_base}/api/public/instagram-assets/"
        f"{business_id}/{version_id}/{asset_id}?{query}"
    )


def verify_signed_asset_request(
    settings: Settings,
    *,
    business_id: int,
    version_id: int,
    asset_id: int,
    expires: int,
    signature: str,
    now: int | None = None,
) -> None:
    clock = now if now is not None else int(time.time())
    if expires < clock or expires > clock + settings.instagram_asset_url_ttl_seconds:
        raise SignedAssetURLInvalid("Signed asset URL has expired")
    expected = _signature(settings, business_id, version_id, asset_id, expires)
    if len(signature) != len(expected) or not hmac.compare_digest(signature, expected):
        raise SignedAssetURLInvalid("Signed asset URL is invalid")


def resolve_authorized_final_asset(
    db: Session, *, business_id: int, version_id: int, asset_id: int
) -> ResolvedSignedAsset:
    row = (
        db.query(InstagramFinalAsset, InstagramContentVersion, InstagramContent)
        .join(
            InstagramContentVersionAsset,
            InstagramContentVersionAsset.asset_id == InstagramFinalAsset.id,
        )
        .join(
            InstagramContentVersion,
            InstagramContentVersion.id == InstagramContentVersionAsset.version_id,
        )
        .join(InstagramContent, InstagramContent.id == InstagramContentVersion.content_id)
        .filter(
            InstagramFinalAsset.id == asset_id,
            InstagramFinalAsset.business_id == business_id,
            InstagramContentVersion.id == version_id,
            InstagramContentVersion.business_id == business_id,
            InstagramContent.business_id == business_id,
            InstagramContent.status == "scheduled",
        )
        .first()
    )
    if row is None:
        raise SignedAssetURLInvalid("Final asset is unavailable")
    asset, version, content = row
    latest = (
        db.query(InstagramContentVersion.id)
        .filter(
            InstagramContentVersion.business_id == business_id,
            InstagramContentVersion.content_id == content.id,
        )
        .order_by(InstagramContentVersion.version_number.desc())
        .first()
    )
    validation = (
        db.query(InstagramContentValidation.id)
        .filter(
            InstagramContentValidation.business_id == business_id,
            InstagramContentValidation.content_id == content.id,
            InstagramContentValidation.version_id == version.id,
            InstagramContentValidation.invalidated_at.is_(None),
        )
        .first()
    )
    if latest is None or latest[0] != version.id or validation is None:
        raise SignedAssetURLInvalid("Final asset is unavailable")
    path = resolve_private_asset_path(asset.storage_key)
    if not path.is_file() or path.stat().st_size != asset.size_bytes:
        raise SignedAssetURLInvalid("Final asset is unavailable")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if not asset.sha256 or not hmac.compare_digest(asset.sha256, digest.hexdigest()):
        raise SignedAssetURLInvalid("Final asset is unavailable")
    return ResolvedSignedAsset(path, asset.media_type, asset.size_bytes)
