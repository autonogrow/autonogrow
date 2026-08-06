from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

InstagramFormat = Literal["single_image", "carousel"]
CommentKind = Literal["comment", "proposal", "change_request"]


class InstagramServiceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class InstagramValidationDelegationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_can_validate_instagram_content: bool


class InstagramContentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    caption: str = Field(default="", max_length=2200)
    format: InstagramFormat = "single_image"
    planned_publish_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Title is required")
        return normalized


class InstagramMaterialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caption: str = Field(max_length=2200)
    format: InstagramFormat
    asset_ids: list[int] = Field(default_factory=list, max_length=10)
    cover_asset_id: int | None = None


class InstagramPlannedDateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planned_publish_at: datetime | None = None


class InstagramTitleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Title is required")
        return normalized


class InstagramValidationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: int


class InstagramCommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: int
    kind: CommentKind = "comment"
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def strip_body(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Comment is required")
        return normalized
