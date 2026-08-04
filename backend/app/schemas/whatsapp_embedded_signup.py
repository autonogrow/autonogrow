from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WhatsAppEmbeddedSignupStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: Literal["initial_connection", "reconnect", "replacement"] | None = None


class WhatsAppEmbeddedSignupCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str = Field(min_length=32, max_length=512)
    code: str | None = Field(default=None, min_length=4, max_length=4096)
    event_type: str = Field(min_length=1, max_length=80)
    event_name: str = Field(min_length=1, max_length=120)
    meta_business_id: str | None = Field(default=None, max_length=255)
    waba_id: str | None = Field(default=None, max_length=255)
    phone_number_id: str | None = Field(default=None, max_length=255)
