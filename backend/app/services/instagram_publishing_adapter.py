from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class InstagramPublishRequest:
    idempotency_key: str
    business_id: int
    content_id: int
    version_id: int
    caption: str
    format: str
    asset_storage_keys: tuple[str, ...]


@dataclass(frozen=True)
class InstagramPublishResult:
    container_id: str
    media_id: str
    permalink: str
    provider_status: str = "published_simulated"
    metadata: dict[str, str] | None = None


class InstagramPublishingError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class TemporaryPublishingError(InstagramPublishingError):
    pass


class PermanentPublishingError(InstagramPublishingError):
    pass


class UnknownPublishingResult(InstagramPublishingError):
    pass


class InstagramPublishingAdapter(Protocol):
    def publish(self, request: InstagramPublishRequest) -> InstagramPublishResult: ...


SimulationBehavior = Literal[
    "success",
    "temporary_error",
    "permanent_error",
    "timeout",
    "unknown_result",
    "delayed_success",
    "duplicate_response",
]


class SimulatedInstagramPublishingAdapter:
    """Deterministic adapter: a key always maps to the same simulated provider IDs."""

    def __init__(self, behavior: SimulationBehavior = "success", delay_seconds: float = 0.0):
        self.behavior = behavior
        self.delay_seconds = delay_seconds

    def publish(self, request: InstagramPublishRequest) -> InstagramPublishResult:
        if self.behavior == "temporary_error":
            raise TemporaryPublishingError("simulated_temporary", "Temporary simulated failure")
        if self.behavior == "permanent_error":
            raise PermanentPublishingError("simulated_permanent", "Permanent simulated failure")
        if self.behavior == "timeout":
            raise TimeoutError("Simulated provider timeout")
        if self.behavior == "unknown_result":
            raise UnknownPublishingResult(
                "simulated_unknown_result", "Publishing outcome requires manual verification"
            )
        if self.behavior == "delayed_success" and self.delay_seconds > 0:
            time.sleep(self.delay_seconds)
        digest = hashlib.sha256(request.idempotency_key.encode("utf-8")).hexdigest()
        media_id = f"sim-media-{digest[:24]}"
        return InstagramPublishResult(
            container_id=f"sim-container-{digest[24:48]}",
            media_id=media_id,
            permalink=f"https://simulated.invalid/p/{digest[:16]}",
            provider_status=(
                "duplicate_idempotent"
                if self.behavior == "duplicate_response"
                else "published_simulated"
            ),
            metadata={"mode": "simulated", "idempotency_digest": digest[:16]},
        )
