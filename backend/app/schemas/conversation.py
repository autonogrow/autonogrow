from pydantic import BaseModel, Field, field_validator


CHANNELS = {"manual", "whatsapp", "instagram"}
CONVERSATION_STATUSES = {"pending", "replied", "closed"}


class ConversationCreate(BaseModel):
    channel: str = "manual"
    customer_name: str | None = Field(default=None, max_length=200)
    customer_phone: str | None = Field(default=None, max_length=40)
    customer_username: str | None = Field(default=None, max_length=200)
    external_user_id: str | None = Field(default=None, max_length=255)
    initial_message: str | None = Field(default=None, max_length=10000)

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, value: str) -> str:
        if value not in CHANNELS:
            raise ValueError("Invalid channel")
        return value


class ConversationMessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def strip_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message body is required")
        return value


class ConversationStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in CONVERSATION_STATUSES:
            raise ValueError("Invalid conversation status")
        return value


class ConversationTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=10000)
    active: bool = True

    @field_validator("name", "body")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be empty")
        return value


class ConversationTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    body: str | None = Field(default=None, min_length=1, max_length=10000)
    active: bool | None = None

    @field_validator("name", "body")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be empty")
        return value


class TestInboundMessageCreate(BaseModel):
    business_slug: str = Field(min_length=1, max_length=120)
    channel: str
    external_user_id: str = Field(min_length=1, max_length=255)
    customer_name: str | None = Field(default=None, max_length=200)
    customer_phone: str | None = Field(default=None, max_length=40)
    customer_username: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, value: str) -> str:
        if value not in CHANNELS:
            raise ValueError("Invalid channel")
        return value

    @field_validator("body", "external_user_id", "business_slug")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be empty")
        return value
