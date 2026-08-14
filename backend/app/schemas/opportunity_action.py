from datetime import datetime

from pydantic import BaseModel, Field


class OpportunityActionPrepare(BaseModel):
    action_type: str = Field(default="contact_customer", max_length=40)
    conversation_id: int | None = Field(default=None, ge=1)


class OpportunityActionUpdate(BaseModel):
    final_text: str = Field(min_length=1, max_length=4096)


class ManualBookingAttributionCreate(BaseModel):
    booking_id: int = Field(ge=1)


class GrowthMetricsQuery(BaseModel):
    period: str = "30d"
    date_from: datetime | None = None
    date_to: datetime | None = None
