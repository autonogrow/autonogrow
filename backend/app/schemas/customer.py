from pydantic import BaseModel, ConfigDict


class CustomerOut(BaseModel):
    id: int
    name: str
    phone: str | None
    email: str | None
    status: str
    notes: str | None

    model_config = ConfigDict(from_attributes=True)


class CustomerSearchOut(BaseModel):
    id: int
    customer_id: int
    name: str
    phone: str | None
    phone_normalized: str | None
    email: str | None
    status: str
    notes: str | None
    memory_eligible: bool
