from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Literal, Protocol

import requests

from app.core.config import Settings, get_settings
from app.services.instagram_meta_client import InstagramMetaClient, MetaHTTPError


class PublishProgressPersistence(Protocol):
    def container_created(self, container_id: str) -> None: ...

    def publishing_started(self) -> None: ...

    def media_published(self, media_id: str) -> None: ...


@dataclass(frozen=True)
class InstagramPublishRequest:
    idempotency_key: str
    business_id: int
    content_id: int
    version_id: int
    caption: str
    format: str
    asset_storage_keys: tuple[str, ...]
    professional_account_id: str | None = None
    access_token: str | None = None
    asset_url: str | None = None
    existing_container_id: str | None = None
    existing_media_id: str | None = None
    progress: PublishProgressPersistence | None = None


@dataclass(frozen=True)
class InstagramPublishResult:
    container_id: str
    media_id: str
    permalink: str | None
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


class PublishingActionRequired(InstagramPublishingError):
    pass


class PublishingResultUnknown(InstagramPublishingError):
    pass


class PublishingAuthenticationError(PublishingActionRequired):
    pass


class PublishingValidationError(PermanentPublishingError):
    pass


# Backwards-compatible name used by Sprint 6B tests and injected adapters.
UnknownPublishingResult = PublishingResultUnknown


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
            raise PublishingResultUnknown(
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


class MetaInstagramPublishingAdapter:
    """Publish one already-validated JPEG through the Instagram API."""

    def __init__(self, client: InstagramMetaClient) -> None:
        self.client = client

    @staticmethod
    def _mapped_error(exc: MetaHTTPError) -> InstagramPublishingError:
        suffix = f"_{exc.error_code}" if exc.error_code else ""
        if exc.authentication:
            return PublishingAuthenticationError(
                f"instagram_authentication{suffix}", "Instagram needs to be reconnected"
            )
        if exc.permission:
            return PublishingActionRequired(
                f"instagram_permission{suffix}",
                "Instagram publishing permission requires attention",
            )
        if exc.retryable:
            return TemporaryPublishingError(
                f"instagram_temporary{suffix}", "Instagram is temporarily unavailable"
            )
        return PermanentPublishingError(
            f"instagram_provider_rejected{suffix}", "Instagram rejected the publication"
        )

    def publish(self, request: InstagramPublishRequest) -> InstagramPublishResult:
        if request.format != "single_image" or len(request.asset_storage_keys) != 1:
            raise PublishingValidationError(
                "unsupported_instagram_format", "Only one final image can be published"
            )
        if not request.professional_account_id or not request.access_token or not request.asset_url:
            raise PublishingActionRequired(
                "instagram_publish_configuration_missing",
                "Instagram publishing configuration requires attention",
            )
        container_id = request.existing_container_id
        if not container_id:
            try:
                container_id = self.client.create_image_container(
                    account_id=request.professional_account_id,
                    image_url=request.asset_url,
                    caption=request.caption,
                    access_token=request.access_token,
                )
            except (requests.ConnectTimeout, requests.ReadTimeout) as exc:
                raise TemporaryPublishingError(
                    "instagram_container_timeout", "Instagram container creation timed out"
                ) from exc
            except requests.RequestException as exc:
                raise TemporaryPublishingError(
                    "instagram_container_network", "Instagram is temporarily unavailable"
                ) from exc
            except ValueError as exc:
                raise PublishingActionRequired(
                    "instagram_professional_account_invalid",
                    "Instagram professional account identifier is invalid",
                ) from exc
            except MetaHTTPError as exc:
                raise self._mapped_error(exc) from exc
            if request.progress:
                request.progress.container_created(container_id)

        media_id = request.existing_media_id
        if not media_id:
            if request.progress:
                request.progress.publishing_started()
            try:
                media_id = self.client.publish_container(
                    account_id=request.professional_account_id,
                    container_id=container_id,
                    access_token=request.access_token,
                )
            except (requests.ConnectTimeout, requests.ReadTimeout) as exc:
                inspected = self.client.inspect_container_best_effort(
                    container_id, request.access_token
                )
                raise PublishingResultUnknown(
                    "instagram_publish_timeout_unknown"
                    + (f"_{inspected.lower()}" if inspected else ""),
                    "Publishing outcome requires manual verification",
                ) from exc
            except requests.RequestException as exc:
                inspected = self.client.inspect_container_best_effort(
                    container_id, request.access_token
                )
                raise PublishingResultUnknown(
                    "instagram_publish_network_unknown"
                    + (f"_{inspected.lower()}" if inspected else ""),
                    "Publishing outcome requires manual verification",
                ) from exc
            except ValueError as exc:
                raise PublishingActionRequired(
                    "instagram_provider_identifier_invalid",
                    "Instagram provider identifier is invalid",
                ) from exc
            except MetaHTTPError as exc:
                if exc.error_code == "9007":
                    raise TemporaryPublishingError(
                        "instagram_container_not_ready",
                        "Instagram container is not ready yet",
                    ) from exc
                if exc.retryable:
                    inspected = self.client.inspect_container_best_effort(
                        container_id, request.access_token
                    )
                    raise PublishingResultUnknown(
                        "instagram_publish_provider_unknown"
                        + (f"_{inspected.lower()}" if inspected else ""),
                        "Publishing outcome requires manual verification",
                    ) from exc
                raise self._mapped_error(exc) from exc
            if request.progress:
                request.progress.media_published(media_id)

        permalink: str | None = None
        try:
            permalink = self.client.get_permalink(media_id, request.access_token)
        except (MetaHTTPError, requests.RequestException, ValueError):
            # Publication already succeeded; permalink enrichment is explicitly best effort.
            pass
        return InstagramPublishResult(
            container_id=container_id,
            media_id=media_id,
            permalink=permalink,
            provider_status="published_meta",
            metadata={"mode": "meta", "permalink_available": str(bool(permalink)).lower()},
        )


def get_instagram_publishing_adapter(
    settings: Settings | None = None,
    *,
    client: InstagramMetaClient | None = None,
) -> InstagramPublishingAdapter:
    active = settings or get_settings()
    if active.instagram_publishing_mode == "simulated":
        return SimulatedInstagramPublishingAdapter()
    if not active.instagram_real_publishing_acknowledged:
        raise PublishingActionRequired(
            "real_publishing_not_acknowledged",
            "Real Instagram publishing has not been explicitly acknowledged",
        )
    return MetaInstagramPublishingAdapter(client or InstagramMetaClient(active))
