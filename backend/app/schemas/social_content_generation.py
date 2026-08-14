from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EditorialFormat = Literal["reel", "story", "carousel", "static_post"]


class SocialContentGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: EditorialFormat | None = None


class SocialContentRegenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: EditorialFormat | None = None


class EditorialSlide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=160)
    body: str = Field(max_length=500)
    visual: str = Field(max_length=500)


class EditorialStoryFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=300)
    visual: str = Field(max_length=500)
    cta: str = Field(default="", max_length=160)
    sticker: str = Field(default="", max_length=120)


class EditorialPackageEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook: str = Field(max_length=300)
    headline: str = Field(max_length=200)
    caption: str = Field(max_length=2200)
    cta_text: str = Field(max_length=200)
    on_screen_text: list[str] = Field(default_factory=list, max_length=12)
    visual_direction: str = Field(max_length=1200)
    shot_list: list[str] = Field(default_factory=list, max_length=12)
    slides: list[EditorialSlide] = Field(default_factory=list, max_length=10)
    story_frames: list[EditorialStoryFrame] = Field(default_factory=list, max_length=10)
    hashtags: list[str] = Field(default_factory=list, min_length=3, max_length=8)

    @field_validator("hashtags")
    @classmethod
    def validate_hashtags(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = value.strip()
            if not item.startswith("#") or len(item) > 80 or any(char.isspace() for char in item):
                raise ValueError("Hashtags must start with # and contain no spaces")
            if item.lower() not in {existing.lower() for existing in normalized}:
                normalized.append(item)
        if len(normalized) < 3:
            raise ValueError("At least three distinct hashtags are required")
        return normalized
