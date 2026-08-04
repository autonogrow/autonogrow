from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.core.config import Settings
from app.models import BusinessChannelIntegration


@dataclass(frozen=True)
class IntegrationHealthResult:
    health_status: str
    healthy: bool
    retryable: bool
    blocking: bool
    reconnection_required: bool
    safe_error_code: str | None
    safe_error_message: str | None
    token_expiry_status: str
    subscription_status: str
    asset_status: str
    checked_at: datetime
    next_check_at: datetime
    metadata: dict[str, str | int | float | bool | None] = field(default_factory=dict)


class IntegrationHealthChecker(Protocol):
    def __call__(
        self,
        integration: BusinessChannelIntegration,
        *,
        access_token: str,
        settings: Settings,
        repair_subscription: bool = False,
    ) -> IntegrationHealthResult: ...


class UnsupportedIntegrationHealthProvider(ValueError):
    pass
