from typing import Literal

from pydantic import BaseModel, ConfigDict


class InstagramOAuthStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: Literal["initial_connection", "reconnect", "replacement"] | None = None
