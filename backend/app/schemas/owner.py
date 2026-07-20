from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from app.schemas.branding import COLOR_PALETTES, TEMPLATE_KEYS, resolve_branding, validate_color


class OwnerServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    price_text: str | None = Field(default=None, max_length=80)
    duration_minutes: int = Field(default=30, gt=0, le=1440)
    active: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class OwnerBusinessCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=160)
    headline: str | None = None
    description: str | None = None
    phone: str | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=120)
    address: str | None = None
    schedule: str | None = None
    maps_url: str | None = None
    instagram_url: str | None = None
    reviews_url: str | None = None
    active: bool = True
    services: list[OwnerServiceCreate] = Field(default_factory=list)
    schedule_template: str = Field(default="default_business_hours")
    theme_key: str = "slate_gold"
    template_key: str = "classic"
    primary_color: str | None = None
    secondary_color: str | None = None
    accent_color: str | None = None
    background_color: str | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value

    @field_validator("schedule_template")
    @classmethod
    def validate_schedule_template(cls, value: str) -> str:
        allowed = {"default_business_hours", "barberia", "manicura", "taller", "peluqueria", "estetica", "fisioterapia", "entrenamiento_personal", "psicologia", "clinica_dental", "masajes", "custom"}
        if value not in allowed:
            raise ValueError(f"Schedule template must be one of: {', '.join(sorted(allowed))}")
        return value

    @model_validator(mode="after")
    def apply_brand_defaults(self):
        values = resolve_branding(self.model_dump(), fill_defaults=True)
        for field in ("theme_key", "primary_color", "secondary_color", "accent_color", "background_color"):
            setattr(self, field, values[field])
        if self.template_key not in TEMPLATE_KEYS:
            raise ValueError("Plantilla no válida")
        return self

    @field_validator("primary_color", "secondary_color", "accent_color", "background_color", mode="before")
    @classmethod
    def valid_create_color(cls, value, info: ValidationInfo):
        return validate_color(value, info.field_name)


class OwnerBusinessUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=160)
    headline: str | None = None
    description: str | None = None
    phone: str | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=120)
    address: str | None = None
    schedule: str | None = None
    maps_url: str | None = None
    instagram_url: str | None = None
    reviews_url: str | None = None
    active: bool | None = None
    logo_alt: str | None = Field(default=None, max_length=240)
    theme_key: str | None = None
    template_key: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    accent_color: str | None = None
    background_color: str | None = None

    @field_validator("name")
    @classmethod
    def strip_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value

    @field_validator("primary_color", "secondary_color", "accent_color", "background_color", mode="before")
    @classmethod
    def valid_update_color(cls, value, info: ValidationInfo):
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


class OwnerBusinessUserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = "business_admin"

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Email inválido")
        return value

    @field_validator("role")
    @classmethod
    def valid_role(cls, value: str) -> str:
        if value not in {"business_admin", "business_staff"}:
            raise ValueError("Role must be business_admin or business_staff")
        return value


class OwnerBusinessUserUpdate(BaseModel):
    role: str | None = None
    active: bool | None = None

    @field_validator("role")
    @classmethod
    def valid_optional_role(cls, value: str | None) -> str | None:
        if value is not None and value not in {"business_admin", "business_staff"}:
            raise ValueError("Role must be business_admin or business_staff")
        return value
