from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

STORY_RENDERER_VERSION = "story-pillow-v1"
_BACKGROUND_RGB = {
    "dark": (17, 24, 39),
    "light": (248, 250, 252),
}
_SOURCE_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
_MAX_SOURCE_PIXELS = 40_000_000


class StoryRenderError(ValueError):
    pass


@dataclass(frozen=True)
class StoryTransform:
    mode: str = "fill"
    zoom: float = 1.0
    position_x: float = 0.5
    position_y: float = 0.5
    background: str = "dark"

    @classmethod
    def from_json(cls, raw: str | None) -> StoryTransform:
        try:
            payload = json.loads(raw or "{}")
        except (TypeError, ValueError) as error:
            raise StoryRenderError("Invalid Story transform") from error
        if not isinstance(payload, dict):
            raise StoryRenderError("Invalid Story transform")
        mode = payload.get("mode", "fill")
        background = payload.get("background", "dark")
        if mode not in {"fill", "fit"}:
            raise StoryRenderError("Invalid Story fit mode")
        if background not in _BACKGROUND_RGB:
            raise StoryRenderError("Invalid Story background")
        try:
            zoom = float(payload.get("zoom", 1.0))
            position_x = float(payload.get("position_x", 0.5))
            position_y = float(payload.get("position_y", 0.5))
        except (TypeError, ValueError) as error:
            raise StoryRenderError("Invalid Story transform values") from error
        values = (zoom, position_x, position_y)
        if not all(math.isfinite(value) for value in values):
            raise StoryRenderError("Invalid Story transform values")
        if not 1.0 <= zoom <= 2.5:
            raise StoryRenderError("Story zoom must be between 1 and 2.5")
        if not 0.0 <= position_x <= 1.0 or not 0.0 <= position_y <= 1.0:
            raise StoryRenderError("Story position must be between 0 and 1")
        return cls(mode, zoom, position_x, position_y, background)

    def to_json(self) -> str:
        return json.dumps(
            {
                "background": self.background,
                "mode": self.mode,
                "position_x": round(self.position_x, 4),
                "position_y": round(self.position_y, 4),
                "zoom": round(self.zoom, 4),
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def story_geometry(
    *,
    source_width: int,
    source_height: int,
    canvas_width: int,
    canvas_height: int,
    transform: StoryTransform,
) -> tuple[int, int, int, int]:
    if min(source_width, source_height, canvas_width, canvas_height) <= 0:
        raise StoryRenderError("Invalid image geometry")
    width_scale = canvas_width / source_width
    height_scale = canvas_height / source_height
    base_scale = (
        max(width_scale, height_scale)
        if transform.mode == "fill"
        else min(width_scale, height_scale)
    )
    scale = base_scale * transform.zoom
    rendered_width = max(1, math.floor(source_width * scale + 0.5))
    rendered_height = max(1, math.floor(source_height * scale + 0.5))
    if rendered_width <= canvas_width:
        offset_x = math.floor((canvas_width - rendered_width) * transform.position_x + 0.5)
    else:
        offset_x = -math.floor((rendered_width - canvas_width) * transform.position_x + 0.5)
    if rendered_height <= canvas_height:
        offset_y = math.floor((canvas_height - rendered_height) * transform.position_y + 0.5)
    else:
        offset_y = -math.floor((rendered_height - canvas_height) * transform.position_y + 0.5)
    return rendered_width, rendered_height, offset_x, offset_y


def _canvas_size(source_width: int) -> tuple[int, int]:
    if source_width >= 1080:
        width = 1080
    elif source_width >= 360:
        width = max(360, (source_width // 9) * 9)
    else:
        width = 360
    return width, width * 16 // 9


def render_story_jpeg(
    source: bytes | Path,
    *,
    transform: StoryTransform,
    max_output_bytes: int,
) -> bytes:
    if max_output_bytes <= 0:
        raise StoryRenderError("Invalid Story output limit")
    stream = io.BytesIO(source) if isinstance(source, bytes) else source
    try:
        with Image.open(stream) as opened:
            if opened.format not in _SOURCE_FORMATS:
                raise StoryRenderError("Unsupported Story image format")
            if opened.width * opened.height > _MAX_SOURCE_PIXELS:
                raise StoryRenderError("Story source image is too large")
            opened.verify()
        stream = io.BytesIO(source) if isinstance(source, bytes) else source
        with Image.open(stream) as reopened:
            image = ImageOps.exif_transpose(reopened).convert("RGB")
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise StoryRenderError("Invalid Story source image") from error

    canvas_width, canvas_height = _canvas_size(image.width)
    rendered_width, rendered_height, offset_x, offset_y = story_geometry(
        source_width=image.width,
        source_height=image.height,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        transform=transform,
    )
    resized = image.resize((rendered_width, rendered_height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (canvas_width, canvas_height), _BACKGROUND_RGB[transform.background])
    canvas.paste(resized, (offset_x, offset_y))
    for quality in (92, 88, 84, 80, 76, 72):
        output = io.BytesIO()
        canvas.save(output, format="JPEG", quality=quality, optimize=True, subsampling=0)
        value = output.getvalue()
        if len(value) <= max_output_bytes:
            return value
    raise StoryRenderError("Rendered Story exceeds the output size limit")


def story_derivation_fingerprint(source_sha256: str, transform: StoryTransform) -> str:
    value = f"{STORY_RENDERER_VERSION}:{source_sha256}:{transform.to_json()}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
