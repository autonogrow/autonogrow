from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChannelAccessGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_policy: Literal["business_admin", "owner_only"] = "business_admin"
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Reason is required")
        return normalized


class SimulatedConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_meta_authority: Literal[True]


class ChannelDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Reason is required")
        return normalized


class ChannelCapabilitiesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    integrated_delivery_enabled: bool | None = None
    automation_enabled: bool | None = None
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Reason is required")
        return normalized
