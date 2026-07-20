from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

from app.schemas.branding import COLOR_PALETTES, TEMPLATE_KEYS, resolve_branding, validate_color


class BusinessCreate(BaseModel):
    slug: str
    name: str
    category: str | None = None
    headline: str | None = None
    description: str | None = None
    phone: str | None = None
    city: str | None = None
    address: str | None = None
    schedule: str | None = None
    maps_url: str | None = None
    instagram_url: str | None = None
    reviews_url: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    accent_color: str | None = None
    background_color: str | None = None
    theme_key: str | None = None
    template_key: str | None = None
    logo_url: str | None = None
    logo_alt: str | None = None

    @model_validator(mode="after")
    def apply_brand_defaults(self):
        values = resolve_branding(self.model_dump(), fill_defaults=True)
        for field in ("theme_key", "primary_color", "secondary_color", "accent_color", "background_color"):
            setattr(self, field, values[field])
        self.template_key = self.template_key if self.template_key in TEMPLATE_KEYS else "classic"
        return self


class BusinessOut(BusinessCreate):
    id: int
    status: str

    model_config = ConfigDict(from_attributes=True)


class BusinessSettingsUpdate(BaseModel):
    name: str
    category: str | None = None
    headline: str | None = None
    description: str | None = None
    phone: str | None = None
    city: str | None = None
    address: str | None = None
    schedule: str | None = None
    maps_url: str | None = None
    instagram_url: str | None = None
    reviews_url: str | None = None
    active: bool
    logo_alt: str | None = None
    theme_key: str | None = None
    template_key: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    accent_color: str | None = None
    background_color: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value

    @field_validator(
        "category",
        "headline",
        "description",
        "phone",
        "city",
        "address",
        "schedule",
        "maps_url",
        "instagram_url",
        "reviews_url",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("primary_color", "secondary_color", "accent_color", "background_color", mode="before")
    @classmethod
    def valid_hex_color(cls, value, info: ValidationInfo):
        return validate_color(value, info.field_name)

    @field_validator("theme_key")
    @classmethod
    def valid_theme(cls, value):
        if value is not None and value not in {*COLOR_PALETTES, "custom"}:
            raise ValueError("Paleta no válida")
        return value

    @field_validator("template_key")
    @classmethod
    def valid_template(cls, value):
        if value is not None and value not in TEMPLATE_KEYS:
            raise ValueError("Plantilla no válida")
        return value
