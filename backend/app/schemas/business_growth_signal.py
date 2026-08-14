from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class BusinessCalendarEventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    ends_at: datetime
    category: str | None = Field(default=None, max_length=80)
    service_id: int | None = None
    enabled: bool = True
    yearly_recurrence: bool = False

    @model_validator(mode="after")
    def normalize_and_validate(self):
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("title cannot be blank")
        self.category = self.category.strip() or None if self.category is not None else None
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class BusinessCalendarEventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    category: str | None = Field(default=None, max_length=80)
    service_id: int | None = None
    enabled: bool | None = None
    yearly_recurrence: bool | None = None

    @model_validator(mode="after")
    def normalize(self):
        if self.title is not None:
            self.title = self.title.strip()
            if not self.title:
                raise ValueError("title cannot be blank")
        if self.category is not None:
            self.category = self.category.strip() or None
        return self
