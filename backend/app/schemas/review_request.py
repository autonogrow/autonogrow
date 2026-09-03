from pydantic import BaseModel, ConfigDict


class ReviewRequestOut(BaseModel):
    id: int
    business_id: int
    booking_id: int
    customer_id: int | None
    customer_name: str
    customer_phone: str | None
    reviews_url: str
    message: str
    status: str
    created_at: str | None = None
    copied_at: str | None = None
    sent_at: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ReviewRequestStatusUpdate(BaseModel):
    status: str
