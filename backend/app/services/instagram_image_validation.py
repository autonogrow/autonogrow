from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.models import InstagramFinalAsset
from app.services.instagram_publishing_adapter import PublishingValidationError

MAX_INSTAGRAM_IMAGE_BYTES = 8 * 1024 * 1024
MIN_WIDTH = 320
MAX_WIDTH = 1440
MIN_ASPECT_RATIO = 0.8
MAX_ASPECT_RATIO = 1.91
STORY_ASPECT_RATIO = 9 / 16
STORY_ASPECT_RATIO_TOLERANCE = 0.01


@dataclass(frozen=True)
class ValidatedInstagramImage:
    path: Path
    sha256: str
    width: int
    height: int
    size_bytes: int


def validate_instagram_caption(caption: str) -> None:
    if len(caption) > 2200:
        raise PublishingValidationError(
            "instagram_caption_too_long", "Instagram caption exceeds 2200 characters"
        )
    if "\x00" in caption:
        raise PublishingValidationError(
            "instagram_caption_invalid", "Instagram caption contains unsupported characters"
        )
    try:
        caption.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise PublishingValidationError(
            "instagram_caption_encoding", "Instagram caption is not valid UTF-8"
        ) from exc


def _validate_instagram_jpeg(
    asset: InstagramFinalAsset,
    path: Path,
) -> ValidatedInstagramImage:
    if asset.media_type != "image/jpeg" or path.suffix.lower() not in {".jpg", ".jpeg"}:
        raise PublishingValidationError(
            "instagram_image_type_unsupported", "Real publishing requires one JPEG image"
        )
    if not path.is_file():
        raise PublishingValidationError("instagram_image_missing", "Final image is unavailable")
    size = path.stat().st_size
    if size <= 0 or size != asset.size_bytes or size > MAX_INSTAGRAM_IMAGE_BYTES:
        raise PublishingValidationError(
            "instagram_image_size_invalid", "Final image size is invalid"
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum = digest.hexdigest()
    if not asset.sha256 or not hmac.compare_digest(asset.sha256, checksum):
        raise PublishingValidationError(
            "instagram_image_checksum_mismatch", "Final image integrity check failed"
        )
    try:
        with Image.open(path) as image:
            if image.format != "JPEG":
                raise PublishingValidationError(
                    "instagram_image_decode_mismatch", "Final image is not a valid JPEG"
                )
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
    except PublishingValidationError:
        raise
    except (Image.DecompressionBombError, OSError, UnidentifiedImageError) as exc:
        raise PublishingValidationError(
            "instagram_image_decode_failed", "Final image could not be decoded safely"
        ) from exc
    if height <= 0 or width < MIN_WIDTH or width > MAX_WIDTH:
        raise PublishingValidationError(
            "instagram_image_dimensions_invalid", "Final image dimensions are not supported"
        )
    return ValidatedInstagramImage(path, checksum, width, height, size)


def validate_instagram_image(
    asset: InstagramFinalAsset,
    path: Path,
) -> ValidatedInstagramImage:
    validated = _validate_instagram_jpeg(asset, path)
    aspect_ratio = validated.width / validated.height
    if not MIN_ASPECT_RATIO <= aspect_ratio <= MAX_ASPECT_RATIO:
        raise PublishingValidationError(
            "instagram_image_aspect_ratio_invalid", "Final image aspect ratio is not supported"
        )
    return validated


def validate_instagram_story_image(
    asset: InstagramFinalAsset,
    path: Path,
) -> ValidatedInstagramImage:
    validated = _validate_instagram_jpeg(asset, path)
    aspect_ratio = validated.width / validated.height
    if abs(aspect_ratio - STORY_ASPECT_RATIO) > STORY_ASPECT_RATIO_TOLERANCE:
        raise PublishingValidationError(
            "instagram_story_image_aspect_ratio_invalid",
            "Instagram Story image must use a 9:16 aspect ratio",
        )
    return validated