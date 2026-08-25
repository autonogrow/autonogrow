from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SocialIdeaAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["visibility", "promotion"] = "visibility"


class SocialIdeaAdminReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "adjust", "reject"]
    note: str | None = Field(default=None, max_length=4000)
    format: Literal["reel", "story", "carousel", "static_post"] | None = None
    objective: Literal[
        "increase_bookings",
        "reactivate_customers",
        "promote_service",
        "seasonal_activation",
        "social_proof",
        "educate",
        "engagement",
        "fill_capacity",
    ] | None = None
    cta: Literal[
        "book_now",
        "check_availability",
        "contact_us",
        "learn_more",
        "discover_service",
        "none",
    ] | None = None
    angle: Literal[
        "availability",
        "before_after",
        "process",
        "faq",
        "benefit",
        "testimonial",
        "seasonal",
        "limited_window",
        "educational",
        "behind_the_scenes",
    ] | None = None

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        return normalized or None

    @model_validator(mode="after")
    def validate_decision(self):
        adjustments = (self.format, self.objective, self.cta, self.angle)
        if self.decision == "adjust" and not any(item is not None for item in adjustments):
            raise ValueError("An adjustment must change at least one allowed field")
        if self.decision == "reject" and self.note is None:
            raise ValueError("A rejection note is required")
        return self


class SocialPromotionProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discount_type: Literal["percent", "fixed"]
    discount_value: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    regular_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    promotional_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    valid_from: datetime
    valid_until: datetime
    days: list[int] = Field(default_factory=list, max_length=7)
    scope: str = Field(min_length=1, max_length=240)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("days")
    @classmethod
    def validate_days(cls, values: list[int]) -> list[int]:
        normalized = sorted(set(values))
        if any(value < 0 or value > 6 for value in normalized):
            raise ValueError("Promotion days must be between 0 and 6")
        return normalized

    @field_validator("scope")
    @classmethod
    def normalize_scope(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_offer(self):
        if self.valid_until <= self.valid_from:
            raise ValueError("Promotion end must be after start")
        if self.promotional_price >= self.regular_price:
            raise ValueError("Promotional price must be lower than regular price")
        expected = (
            self.regular_price * (Decimal("1") - self.discount_value / Decimal("100"))
            if self.discount_type == "percent"
            else self.regular_price - self.discount_value
        ).quantize(Decimal("0.01"))
        if expected != self.promotional_price:
            raise ValueError("Promotional price does not match the discount")
        return self


class SocialPromotionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: int = Field(gt=0)
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=4000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        return normalized or None
