from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

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
    public_name: str | None = Field(default=None, max_length=200)
    bookable: bool = False
    show_schedule: bool = True
    bio: str | None = Field(default=None, max_length=2000)

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
    public_name: str | None = Field(default=None, max_length=200)
    bookable: bool | None = None
    show_schedule: bool | None = None
    bio: str | None = Field(default=None, max_length=2000)

    @field_validator("role")
    @classmethod
    def valid_optional_role(cls, value: str | None) -> str | None:
        if value is not None and value not in {"business_admin", "business_staff"}:
            raise ValueError("Role must be business_admin or business_staff")
        return value


class OwnerIncidentUpdate(BaseModel):
    action: str

    @field_validator("action")
    @classmethod
    def valid_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"acknowledge", "resolve", "ignore", "reopen"}:
            raise ValueError("Action must be acknowledge, resolve, ignore or reopen")
        return normalized


OWNER_AUTOMATION_LIMIT_MAX = 1_000_000
OWNER_LIMIT_BEHAVIORS = {"semi_automatic", "disabled"}


class OwnerBusinessAutomationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: str | None = Field(default=None, max_length=60, pattern=r"^[a-z0-9_-]+$")
    auto_limit_per_period: int | None = Field(
        default=None, ge=0, le=OWNER_AUTOMATION_LIMIT_MAX
    )
    on_limit_reached: str | None = None
    allowed_limit_behaviors: list[str] | None = Field(default=None, min_length=1, max_length=2)
    automation_feature_enabled: bool | None = None
    instagram_channel_enabled: bool | None = None
    whatsapp_channel_enabled: bool | None = None
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("on_limit_reached")
    @classmethod
    def valid_limit_behavior(cls, value: str | None) -> str | None:
        if value is not None and value not in OWNER_LIMIT_BEHAVIORS:
            raise ValueError("Invalid limit behavior")
        return value

    @field_validator("allowed_limit_behaviors")
    @classmethod
    def valid_allowed_behaviors(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if len(set(value)) != len(value) or any(item not in OWNER_LIMIT_BEHAVIORS for item in value):
            raise ValueError("Invalid or duplicated limit behavior")
        return value

    @field_validator("reason")
    @classmethod
    def strip_optional_reason(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


class OwnerAutomationUsageAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_usage: int = Field(ge=0, le=OWNER_AUTOMATION_LIMIT_MAX)
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_adjustment_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Reason is required")
        return value


class OwnerAutomationPeriodRenewal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)
    amount: float | None = Field(default=None, ge=0, le=10_000_000)
    payment_method: str | None = Field(
        default=None, max_length=60, pattern=r"^[a-z0-9_-]+$"
    )
    external_reference: str | None = Field(default=None, max_length=120)
    confirm_active_period: bool = False

    @field_validator("reason")
    @classmethod
    def strip_renewal_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Reason is required")
        return value

    @field_validator("payment_method")
    @classmethod
    def strip_optional_payment_text(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @field_validator("external_reference")
    @classmethod
    def reject_card_number_reference(cls, value: str | None) -> str | None:
        value = value.strip() if value and value.strip() else None
        if value is None:
            return None
        compact = value.replace(" ", "").replace("-", "")
        if compact.isdigit() and 13 <= len(compact) <= 19:
            raise ValueError("Card numbers must not be stored as payment references")
        return value


class OwnerAutomationPeriodAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)
    period_started_at: datetime
    period_ends_at: datetime
    period_status: str = "active"
    confirm_no_payment: bool

    @field_validator("reason")
    @classmethod
    def strip_period_adjustment_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Reason is required")
        return value

    @field_validator("period_started_at", "period_ends_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("A UTC offset is required")
        return value

    @field_validator("period_status")
    @classmethod
    def valid_adjusted_status(cls, value: str) -> str:
        if value not in {"active", "pending_renewal"}:
            raise ValueError("Period status must be active or pending_renewal")
        return value

    @model_validator(mode="after")
    def validate_period_adjustment(self):
        if not self.confirm_no_payment:
            raise ValueError("The non-payment administrative correction must be confirmed")
        if self.period_ends_at <= self.period_started_at:
            raise ValueError("Period end must be after period start")
        return self
