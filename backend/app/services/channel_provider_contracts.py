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


@dataclass(frozen=True)
class InboxProcessResult:
    action: str
    automation: dict | None = None


class ChannelInboxProcessingError(ValueError):
    error_code = "channel_inbox_processing_failed"
    safe_message = "Channel inbox processing failed"
    retryable = True

    def __init__(
        self,
        message: str | None = None,
        *,
        error_code: str | None = None,
        safe_message: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        if error_code is not None:
            self.error_code = error_code
        if safe_message is not None:
            self.safe_message = safe_message
        if retryable is not None:
            self.retryable = retryable
        super().__init__(message or self.safe_message)


class InvalidChannelInboxPayload(ChannelInboxProcessingError):
    error_code = "invalid_payload"
    safe_message = "Stored webhook event is invalid"
    retryable = False


class UnsupportedChannelProvider(ChannelInboxProcessingError):
    error_code = "unsupported_channel_provider"
    safe_message = "Channel provider is not supported"
    retryable = False

    def __init__(self, provider: str, *, operation: str) -> None:
        self.provider = provider
        self.operation = operation
        super().__init__(self.safe_message)
