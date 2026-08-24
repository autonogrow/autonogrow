from __future__ import annotations

import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import requests
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings, get_uploads_dir
from app.models import (
    BusinessChannelIntegration,
    InstagramRawAsset,
    InstagramRemoteMedia,
)
from app.services.instagram_meta_client import InstagramMetaClient, InstagramRemoteMediaItem
from app.services.integration_crypto_service import IntegrationCryptoError, decrypt_secret

_ALLOWED_IMAGE_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_SOURCE_PIXELS = 40_000_000


class RemoteAssetError(ValueError):
    pass


@dataclass(frozen=True)
class DownloadedImage:
    content: bytes
    media_type: str
    extension: str
    sha256: str


def _validate_public_https_url(
    url: str,
    *,
    resolver: Callable[..., list[tuple]] = socket.getaddrinfo,
) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or len(url) > 8192
    ):
        raise RemoteAssetError("Unsafe remote media URL")
    try:
        addresses = resolver(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise RemoteAssetError("Remote media host could not be resolved") from error
    if not addresses:
        raise RemoteAssetError("Remote media host could not be resolved")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise RemoteAssetError("Remote media host is not public")


def _validate_downloaded_image(content: bytes, media_type: str) -> str:
    signatures = {
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP",
    }
    if not signatures.get(media_type, False):
        raise RemoteAssetError("Remote media content does not match its MIME type")
    try:
        from io import BytesIO

        with Image.open(BytesIO(content)) as image:
            if image.width * image.height > _MAX_SOURCE_PIXELS:
                raise RemoteAssetError("Remote image is too large to decode")
            image.verify()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise RemoteAssetError("Remote image is invalid") from error
    return {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[media_type]


def download_remote_image(
    url: str,
    *,
    settings: Settings | None = None,
    session: requests.Session | None = None,
    resolver: Callable[..., list[tuple]] = socket.getaddrinfo,
) -> DownloadedImage:
    config = settings or get_settings()
    http = session or requests.Session()
    maximum = config.instagram_remote_download_max_size_mb * 1024 * 1024
    current_url = url
    for redirect_count in range(4):
        hostname = (urlsplit(current_url).hostname or "").lower()
        if config.app_env in {"staging", "production"} and not (
            hostname.endswith(".cdninstagram.com")
            or hostname == "cdninstagram.com"
            or hostname.endswith(".fbcdn.net")
            or hostname == "fbcdn.net"
        ):
            raise RemoteAssetError("Remote media host is not an approved Meta CDN")
        _validate_public_https_url(current_url, resolver=resolver)
        try:
            response = http.get(
                current_url,
                headers={
                    "Accept": "image/jpeg,image/png,image/webp",
                    "User-Agent": "AutonoGrow/1.0",
                },
                timeout=(
                    config.instagram_http_connect_timeout_seconds,
                    config.instagram_http_read_timeout_seconds,
                ),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as error:
            raise RemoteAssetError("Remote media could not be downloaded") from error
        try:
            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("Location")
                if not location or redirect_count >= 3:
                    raise RemoteAssetError("Remote media redirected too many times")
                current_url = urljoin(current_url, location)
                continue
            if response.status_code != 200:
                raise RemoteAssetError("Remote media could not be downloaded")
            raw_length = response.headers.get("Content-Length")
            if raw_length:
                try:
                    if int(raw_length) > maximum:
                        raise RemoteAssetError("Remote media exceeds the download limit")
                except ValueError as error:
                    raise RemoteAssetError("Invalid remote media length") from error
            media_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            if media_type not in _ALLOWED_IMAGE_MIME:
                raise RemoteAssetError("Remote media is not a supported image")
            chunks: list[bytes] = []
            size = 0
            try:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > maximum:
                        raise RemoteAssetError("Remote media exceeds the download limit")
                    chunks.append(chunk)
            except requests.RequestException as error:
                raise RemoteAssetError("Remote media download was interrupted") from error
            content = b"".join(chunks)
            if not content:
                raise RemoteAssetError("Remote media is empty")
            extension = _validate_downloaded_image(content, media_type)
            return DownloadedImage(
                content=content,
                media_type=media_type,
                extension=extension,
                sha256=hashlib.sha256(content).hexdigest(),
            )
        finally:
            response.close()
    raise RemoteAssetError("Remote media redirected too many times")


def remote_media_for_business(
    db: Session,
    *,
    business_id: int,
    media_id: int,
    require_available: bool = True,
) -> tuple[InstagramRemoteMedia, BusinessChannelIntegration]:
    query = (
        db.query(InstagramRemoteMedia, BusinessChannelIntegration)
        .join(
            BusinessChannelIntegration,
            BusinessChannelIntegration.id == InstagramRemoteMedia.integration_id,
        )
        .filter(
            InstagramRemoteMedia.id == media_id,
            InstagramRemoteMedia.business_id == business_id,
            BusinessChannelIntegration.business_id == business_id,
            BusinessChannelIntegration.channel == "instagram",
            BusinessChannelIntegration.provider == "instagram",
            BusinessChannelIntegration.integration_status.in_(("connected", "degraded")),
        )
    )
    if require_available:
        query = query.filter(InstagramRemoteMedia.remote_status == "available")
    row = query.first()
    if row is None:
        raise RemoteAssetError("Instagram media is unavailable")
    return row[0], row[1]


def refresh_remote_media_item(
    media: InstagramRemoteMedia,
    integration: BusinessChannelIntegration,
    *,
    settings: Settings | None = None,
    client: InstagramMetaClient | None = None,
) -> InstagramRemoteMediaItem:
    config = settings or get_settings()
    try:
        token = decrypt_secret(
            integration.encrypted_access_token or "",
            integration.encryption_key_version or "",
            settings=config,
        )
    except IntegrationCryptoError as error:
        raise RemoteAssetError("Instagram integration credentials are unavailable") from error
    meta = client or InstagramMetaClient(config)
    item = meta.get_media(media_id=media.provider_media_id, access_token=token)
    if item.provider_media_id != media.provider_media_id:
        raise RemoteAssetError("Instagram returned an unexpected media identity")
    return item


def materialize_remote_image(
    db: Session,
    *,
    media: InstagramRemoteMedia,
    downloaded: DownloadedImage,
) -> tuple[InstagramRawAsset, bool]:
    if media.media_type != "IMAGE":
        raise RemoteAssetError("Only Instagram images can be materialized in P1")
    query = db.query(InstagramRemoteMedia).filter(
        InstagramRemoteMedia.id == media.id,
        InstagramRemoteMedia.business_id == media.business_id,
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    locked_media = query.one()
    existing = (
        db.query(InstagramRawAsset)
        .filter(
            InstagramRawAsset.business_id == locked_media.business_id,
            InstagramRawAsset.source_remote_media_id == locked_media.id,
        )
        .first()
    )
    if existing is not None:
        return existing, False
    relative = (
        Path("_instagram_content")
        / str(locked_media.business_id)
        / "raw"
        / "instagram"
        / f"{uuid4().hex}{downloaded.extension}"
    )
    path = get_uploads_dir() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(downloaded.content)
    asset = InstagramRawAsset(
        business_id=locked_media.business_id,
        uploaded_by_user_id=None,
        source_kind="instagram",
        source_remote_media_id=locked_media.id,
        original_filename=f"instagram-{locked_media.id}{downloaded.extension}",
        storage_key=relative.as_posix(),
        media_type=downloaded.media_type,
        size_bytes=len(downloaded.content),
        sha256=downloaded.sha256,
        label="Contenido sincronizado desde Instagram",
    )
    db.add(asset)
    db.flush()
    return asset, True
