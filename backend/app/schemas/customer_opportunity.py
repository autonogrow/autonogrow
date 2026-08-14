from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class OpportunityStatusUpdate(BaseModel):
    status: str


class ScheduledFollowUpCreate(BaseModel):
    customer_id: int
    due_at: datetime
    booking_id: int | None = None
    service_id: int | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def strip_note(self):
        if self.note is not None:
            self.note = self.note.strip() or None
        return self
