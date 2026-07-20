from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServiceCreate(BaseModel):
    name: str
    description: str | None = None
    price_text: str | None = None
    duration_text: str | None = None
    duration_minutes: int | None = None


class ServiceOut(ServiceCreate):
    id: int
    active: bool
    business_slug: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AdminServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    price_text: str | None = Field(default=None, max_length=80)
    duration_minutes: int = Field(gt=0, le=1440)
    active: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class AdminServiceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    price_text: str | None = Field(default=None, max_length=80)
    duration_minutes: int | None = Field(default=None, gt=0, le=1440)
    active: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value
