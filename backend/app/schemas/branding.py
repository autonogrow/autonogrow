import re

from pydantic import BaseModel, Field, field_validator

COLOR_PALETTES = {
    "slate_gold": {"primary_color": "#334155", "secondary_color": "#0f172a", "accent_color": "#f59e0b", "background_color": "#f8fafc"},
    "rose_beauty": {"primary_color": "#be123c", "secondary_color": "#831843", "accent_color": "#f9a8d4", "background_color": "#fff1f2"},
    "emerald_clean": {"primary_color": "#047857", "secondary_color": "#064e3b", "accent_color": "#6ee7b7", "background_color": "#ecfdf5"},
    "blue_clinic": {"primary_color": "#2563eb", "secondary_color": "#1e3a8a", "accent_color": "#93c5fd", "background_color": "#eff6ff"},
    "amber_barber": {"primary_color": "#92400e", "secondary_color": "#451a03", "accent_color": "#fbbf24", "background_color": "#fffbeb"},
    "violet_modern": {"primary_color": "#7c3aed", "secondary_color": "#4c1d95", "accent_color": "#c4b5fd", "background_color": "#f5f3ff"},
}
SAFE_COLORS = {
    "primary_color": "#334155",
    "secondary_color": "#0f172a",
    "accent_color": "#f59e0b",
    "background_color": "#f8fafc",
}
TEMPLATE_KEYS = {"classic", "elegant", "beauty", "clinic", "urban", "minimal"}
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def resolve_branding(values: dict, *, fill_defaults: bool = False) -> dict:
    theme_key = values.get("theme_key")
    if theme_key in COLOR_PALETTES:
        for field, color in COLOR_PALETTES[theme_key].items():
            if fill_defaults or not values.get(field):
                values[field] = color
    elif fill_defaults:
        values["theme_key"] = theme_key if theme_key == "custom" else "slate_gold"
        for field, color in SAFE_COLORS.items():
            values[field] = values.get(field) or color
    return values


class GalleryImageUpdate(BaseModel):
    alt_text: str | None = Field(default=None, max_length=240)
    position: int | None = Field(default=None, ge=0)
    active: bool | None = None

    @field_validator("alt_text", mode="before")
    @classmethod
    def clean_alt(cls, value):
        return value.strip() or None if isinstance(value, str) else value


def validate_color(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return SAFE_COLORS[field_name]
    if not HEX_COLOR.fullmatch(value):
        raise ValueError("El color debe tener formato #RRGGBB")
    return value.lower()
