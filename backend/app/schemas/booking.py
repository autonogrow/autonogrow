from pydantic import BaseModel, ConfigDict, Field


class BookingRequestCreate(BaseModel):
    customer_name: str = Field(min_length=2, max_length=200)
    customer_phone: str | None = Field(default=None, max_length=40)
    service_id: int | None = None
    service_name: str | None = Field(default=None, min_length=2, max_length=200)
    preferred_date: str | None = Field(default=None, max_length=20)
    preferred_day_label: str | None = Field(default=None, max_length=100)
    preferred_time: str | None = Field(default=None, min_length=2, max_length=20)
    start_datetime: str | None = None
    notes: str | None = Field(default=None, max_length=1000)
    source: str = Field(default="landing", max_length=40)


class BookingOut(BaseModel):
    id: int
    customer_name: str
    customer_phone: str | None
    service_id: int | None = None
    service_name: str
    duration_minutes: int | None = None
    start_datetime: str | None = None
    end_datetime: str | None = None
    preferred_date: str | None
    preferred_day_label: str | None
    preferred_time: str
    notes: str | None
    status: str
    google_sync_status: str
    created_at: str | None = None

    model_config = ConfigDict(from_attributes=True)
