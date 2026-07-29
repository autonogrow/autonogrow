from pydantic import BaseModel, ConfigDict, Field, field_validator


CHANNELS = {"manual", "whatsapp", "instagram"}
CONVERSATION_STATUSES = {"pending", "replied", "closed"}
AUTOMATION_RULE_MODES = {"disabled", "semi_automatic", "automatic"}
HUMAN_REPLY_PAUSE_MINUTES = {0, 15, 60, 240, -1}
CONVERSATION_AUTOMATION_ACTIONS = {"pause", "manual", "resume"}


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
    suggestion_id: int | None = Field(default=None, ge=1)

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


class BusinessAutomationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    automation_enabled: bool | None = None
    auto_threshold: int | None = Field(default=None, ge=0, le=100)
    on_limit_reached: str | None = None
    human_reply_pause_minutes: int | None = None

    @field_validator("on_limit_reached")
    @classmethod
    def validate_limit_mode(cls, value: str | None) -> str | None:
        if value is not None and value not in {"semi_automatic", "disabled"}:
            raise ValueError("Invalid limit mode")
        return value
    @field_validator("human_reply_pause_minutes")
    @classmethod
    def validate_human_pause(cls, value: int | None) -> int | None:
        if value is not None and value not in HUMAN_REPLY_PAUSE_MINUTES:
            raise ValueError("Invalid human reply pause duration")
        return value


# Backwards-compatible import name with the restricted business-admin fields.
ConversationAutomationSettingsUpdate = BusinessAutomationSettingsUpdate


class ConversationAutomationControlUpdate(BaseModel):
    action: str
    duration_minutes: int | None = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        if value not in CONVERSATION_AUTOMATION_ACTIONS:
            raise ValueError("Invalid conversation automation action")
        return value

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, value: int | None) -> int | None:
        if value is not None and value not in {15, 60, 240, -1}:
            raise ValueError("Invalid conversation automation duration")
        return value


class ConversationAutomationRuleUpdate(BaseModel):
    mode: str | None = None
    template_id: int | None = Field(default=None, ge=1)
    active: bool | None = None

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str | None) -> str | None:
        if value is not None and value not in AUTOMATION_RULE_MODES:
            raise ValueError("Invalid automation mode")
        return value


class ConversationSuggestionUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in {"used", "dismissed"}:
            raise ValueError("Invalid suggestion status")
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
