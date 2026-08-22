from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.branding import validate_color


class StrictOnboardingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def safe_optional_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
        raise ValueError("La URL debe usar http o https y no puede incluir credenciales")
    return normalized


class OnboardingStartRequest(StrictOnboardingModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=120)
    template_key: str | None = Field(default=None, max_length=80)
    template_version: int | None = Field(default=None, ge=1)
    modules: list[Literal["essential", "growth", "social"]] = Field(
        default_factory=lambda: ["essential", "growth", "social"], min_length=1, max_length=3
    )

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("modules")
    @classmethod
    def unique_modules(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Los módulos no pueden repetirse")
        if "essential" not in value:
            raise ValueError("Essential es obligatorio en V1")
        return value


class TemplateApplyRequest(StrictOnboardingModel):
    template_key: str = Field(min_length=1, max_length=80)
    template_version: int | None = Field(default=None, ge=1)
    retain_existing: bool = True
    confirm_change: bool = False


class IdentityStepRequest(StrictOnboardingModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    legal_name: str | None = Field(default=None, max_length=240)
    tax_identifier: str | None = Field(default=None, max_length=80)
    language_code: str | None = Field(default=None, pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    timezone: str | None = Field(default=None, max_length=80)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    confirm_active_slug_change: bool = False


class ContactStepRequest(StrictOnboardingModel):
    phone: str | None = Field(default=None, max_length=40)
    whatsapp_phone: str | None = Field(default=None, max_length=40)
    public_email: str | None = Field(default=None, max_length=320)
    city: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=1000)
    postal_code: str | None = Field(default=None, max_length=20)
    region: str | None = Field(default=None, max_length=120)
    country_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    maps_url: str | None = None
    instagram_url: str | None = None
    tiktok_url: str | None = None
    external_website_url: str | None = None

    @field_validator("phone", "whatsapp_phone")
    @classmethod
    def valid_phone(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = re.sub(r"[\s().-]", "", value)
        if not re.fullmatch(r"\+?[1-9][0-9]{7,14}", normalized):
            raise ValueError("El teléfono debe tener formato internacional")
        return normalized

    @field_validator("public_email")
    @classmethod
    def valid_email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Email público inválido")
        return normalized

    @field_validator("maps_url", "instagram_url", "tiktok_url", "external_website_url")
    @classmethod
    def valid_url(cls, value: str | None) -> str | None:
        return safe_optional_url(value)


class OnboardingServiceItem(StrictOnboardingModel):
    id: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=3000)
    duration_minutes: int = Field(gt=0, le=1440)
    price_amount: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    category: str | None = Field(default=None, max_length=120)
    visible: bool = True
    bookable: bool = True
    requires_approval: bool = False
    buffer_before_minutes: int = Field(default=0, ge=0, le=1440)
    buffer_after_minutes: int = Field(default=0, ge=0, le=1440)
    position: int = Field(default=0, ge=0, le=10000)
    active: bool = True

    @field_validator("name")
    @classmethod
    def normalized_name(cls, value: str) -> str:
        return value.strip()


class ServicesStepRequest(StrictOnboardingModel):
    services: list[OnboardingServiceItem] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_names(self):
        names = [item.name.casefold() for item in self.services]
        if len(names) != len(set(names)):
            raise ValueError("Los nombres de servicio no pueden repetirse")
        return self


class StaffItem(StrictOnboardingModel):
    id: int | None = Field(default=None, ge=1)
    public_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    role_label: str = Field(default="professional", min_length=1, max_length=120)
    color: str | None = None
    capacity: int = Field(default=1, ge=1, le=100)
    active: bool = True
    service_ids: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("color", mode="before")
    @classmethod
    def valid_color(cls, value: str | None):
        return validate_color(value, "color")


class StaffStepRequest(StrictOnboardingModel):
    staff: list[StaffItem] = Field(max_length=100)


class TimeWindow(StrictOnboardingModel):
    start: str = Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    end: str = Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("La hora final debe ser posterior a la inicial")
        return self


class SchedulesStepRequest(StrictOnboardingModel):
    timezone: str | None = Field(default=None, max_length=80)
    weekly_schedule: dict[str, list[TimeWindow]]

    @model_validator(mode="after")
    def valid_schedule(self):
        if set(self.weekly_schedule) - {str(day) for day in range(7)}:
            raise ValueError("Los días deben identificarse de 0 a 6")
        for windows in self.weekly_schedule.values():
            ordered = sorted(windows, key=lambda item: item.start)
            if any(
                current.end > following.start for current, following in zip(ordered, ordered[1:])
            ):
                raise ValueError("Los intervalos de horario no pueden solaparse")
        return self


class BookingRulesStepRequest(StrictOnboardingModel):
    min_notice_minutes: int = Field(ge=0, le=525600)
    max_days_ahead: int = Field(gt=0, le=730)
    slot_interval_minutes: int = Field(gt=0, le=720)
    buffer_between_bookings_minutes: int = Field(default=0, ge=0, le=1440)
    auto_confirm_bookings: bool = True
    cancellation_allowed: bool = True
    cancellation_notice_minutes: int = Field(default=120, ge=0, le=525600)
    reschedule_allowed: bool = True
    max_simultaneous_bookings: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def coherent_horizon(self):
        if self.max_days_ahead * 1440 < self.min_notice_minutes:
            raise ValueError("El horizonte máximo debe superar la antelación mínima")
        return self


class BrandingStepRequest(StrictOnboardingModel):
    theme_key: str | None = Field(default=None, max_length=40)
    template_key: str | None = Field(default=None, max_length=40)
    primary_color: str | None = None
    secondary_color: str | None = None
    accent_color: str | None = None
    background_color: str | None = None
    logo_alt: str | None = Field(default=None, max_length=240)

    @field_validator(
        "primary_color", "secondary_color", "accent_color", "background_color", mode="before"
    )
    @classmethod
    def valid_color(cls, value: str | None, info):
        return validate_color(value, info.field_name)


class LandingStepRequest(StrictOnboardingModel):
    headline: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    landing_cta: str | None = Field(default=None, max_length=120)
    schedule: str | None = Field(default=None, max_length=1000)
    reviews_url: str | None = None
    seo_title: str | None = Field(default=None, max_length=160)
    seo_description: str | None = Field(default=None, max_length=320)

    @field_validator("reviews_url")
    @classmethod
    def valid_url(cls, value: str | None) -> str | None:
        return safe_optional_url(value)


class AutomationsStepRequest(StrictOnboardingModel):
    automation_enabled: bool | None = None
    auto_threshold: int | None = Field(default=None, ge=0, le=100)
    human_reply_pause_minutes: int | None = Field(default=None, ge=0, le=10080)
    messages: dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator("messages")
    @classmethod
    def bounded_messages(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {
            "welcome",
            "request_data",
            "out_of_hours",
            "booking_reminder",
            "booking_confirmation",
            "booking_cancellation",
            "booking_reschedule",
            "review_request",
            "reactivation",
            "human_handoff",
        }
        if set(value) - allowed or any(len(text) > 3000 for text in value.values()):
            raise ValueError("Tipo o longitud de automatización no permitidos")
        return {key: text.strip() for key, text in value.items()}


class CreditsPlanStepRequest(StrictOnboardingModel):
    plan_key: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_-]+$")
    included_credits: int = Field(ge=0, le=10_000_000)
    additional_credits: int = Field(default=0, ge=0, le=10_000_000)
    period_days: int = Field(default=30, ge=1, le=366)


CloneSection = Literal[
    "services",
    "schedules",
    "booking_rules",
    "landing_content",
    "automations",
    "branding",
    "staff_roles",
]


class CloneConfigurationRequest(StrictOnboardingModel):
    source_business_id: int = Field(ge=1)
    sections: list[CloneSection] = Field(min_length=1, max_length=7)
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("sections")
    @classmethod
    def unique_sections(cls, value: list[CloneSection]) -> list[CloneSection]:
        if len(value) != len(set(value)):
            raise ValueError("Las secciones de clonación no pueden repetirse")
        return value


class ActivationRequest(StrictOnboardingModel):
    reason: str = Field(min_length=3, max_length=500)
    expected_readiness_version: str = Field(min_length=16, max_length=128)


class BusinessStateReasonRequest(StrictOnboardingModel):
    reason: str = Field(min_length=3, max_length=500)


class StepSkipRequest(StrictOnboardingModel):
    reason: str = Field(min_length=3, max_length=500)
