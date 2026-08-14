from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.customer_memory import MEMORY_CATEGORIES

MEMORY_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


class CustomerMemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    key: str = "note"
    value: str = Field(min_length=1, max_length=2000)
    source_type: str = "manual"
    is_sensitive: bool = False
    expires_at: datetime | None = None
    supersedes_id: int | None = Field(default=None, ge=1)

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        if value not in MEMORY_CATEGORIES:
            raise ValueError("Invalid memory category")
        return value

    @field_validator("source_type")
    @classmethod
    def validate_manual_source(cls, value: str) -> str:
        if value != "manual":
            raise ValueError("Admin-created memories must use the manual source")
        return value

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        value = value.strip().lower()
        if not MEMORY_KEY_PATTERN.fullmatch(value):
            raise ValueError("Memory key must use lowercase letters, numbers and underscores")
        return value

    @field_validator("value")
    @classmethod
    def clean_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Memory content is required")
        return value


class CustomerMemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | None = Field(default=None, min_length=1, max_length=2000)
    is_sensitive: bool | None = None
    expires_at: datetime | None = None

    @field_validator("value")
    @classmethod
    def clean_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Memory content is required")
        return value


class CustomerMemoryReplacement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=2000)
    is_sensitive: bool | None = None
    expires_at: datetime | None = None

    @field_validator("value")
    @classmethod
    def clean_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Memory content is required")
        return value
