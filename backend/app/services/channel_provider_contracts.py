from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSendResult:
    delivery_status: str
    provider_message_id: str | None = None
    error_message: str | None = None
    http_status: int | None = None
    error_code: str | None = None
    error_subcode: str | None = None
    error_type: str | None = None
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.delivery_status == "sent"


ProviderSender = Callable[..., ProviderSendResult]


class InvalidChannelInboxPayload(ValueError):
    error_code = "invalid_payload"
    safe_message = "Stored webhook event is invalid"
    retryable = False


class UnsupportedChannelProvider(ValueError):
    error_code = "unsupported_channel_provider"
    safe_message = "Channel provider is not supported"
    retryable = False

    def __init__(self, provider: str, *, operation: str) -> None:
        self.provider = provider
        self.operation = operation
        super().__init__(self.safe_message)
