from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Literal, Protocol

import requests

from app.core.config import Settings, get_settings
from app.services.instagram_meta_client import InstagramMetaClient, MetaHTTPError


class PublishProgressPersistence(Protocol):
    def carousel_child_created(
        self,
        position: int,
        container_id: str,
    ) -> None: ...

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
    asset_media_types: tuple[str, ...] = ()
    professional_account_id: str | None = None
    access_token: str | None = None
    asset_urls: tuple[str, ...] = ()
    existing_child_container_ids: tuple[str | None, ...] = ()
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
    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        provider_diagnostics: dict[str, str | int | bool | None] | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.provider_diagnostics = provider_diagnostics or {}


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
    """Publish validated Instagram media through the Instagram API."""

    def __init__(self, client: InstagramMetaClient) -> None:
        self.client = client

    @staticmethod
    def _safe_provider_diagnostics(
        exc: MetaHTTPError,
        *,
        operation: str | None = None,
    ) -> dict[str, str | int | bool | None]:
        return {
            "operation": operation or exc.operation,
            "http_status": exc.status_code,
            "error_code": exc.error_code,
            "error_subcode": exc.error_subcode,
            "error_type": exc.error_type,
            "is_transient": exc.is_transient,
            "trace_id": exc.provider_request_id,
        }

    @classmethod
    def _mapped_error(
        cls,
        exc: MetaHTTPError,
        *,
        operation: str | None = None,
    ) -> InstagramPublishingError:
        suffix = f"_{exc.error_code}" if exc.error_code else ""
        diagnostics = cls._safe_provider_diagnostics(exc, operation=operation)
        if exc.authentication:
            return PublishingAuthenticationError(
                f"instagram_authentication{suffix}",
                "Instagram needs to be reconnected",
                provider_diagnostics=diagnostics,
            )
        if exc.permission:
            return PublishingActionRequired(
                f"instagram_permission{suffix}",
                "Instagram publishing permission requires attention",
                provider_diagnostics=diagnostics,
            )
        if exc.retryable:
            return TemporaryPublishingError(
                f"instagram_temporary{suffix}",
                "Instagram is temporarily unavailable",
                provider_diagnostics=diagnostics,
            )
        return PermanentPublishingError(
            f"instagram_provider_rejected{suffix}",
            "Instagram rejected the publication",
            provider_diagnostics=diagnostics,
        )

    def _require_container_finished(
        self,
        request: InstagramPublishRequest,
        *,
        container_id: str,
        code_prefix: str,
        media_label: str,
        operation: str,
        position: int | None = None,
    ) -> None:
        diagnostics: dict[str, str | int | bool | None] = {
            "operation": operation,
            "container_status": None,
        }
        if position is not None:
            diagnostics["carousel_position"] = position

        try:
            container_status = self.client.get_container_status(
                container_id,
                request.access_token or "",
            )
            diagnostics["container_status"] = container_status
        except (requests.ConnectTimeout, requests.ReadTimeout) as exc:
            raise TemporaryPublishingError(
                f"{code_prefix}_status_timeout",
                f"Instagram {media_label} processing status could not be checked yet",
                provider_diagnostics=diagnostics,
            ) from exc
        except requests.RequestException as exc:
            raise TemporaryPublishingError(
                f"{code_prefix}_status_network",
                "Instagram is temporarily unavailable",
                provider_diagnostics=diagnostics,
            ) from exc
        except ValueError as exc:
            raise PublishingActionRequired(
                "instagram_provider_identifier_invalid",
                "Instagram provider identifier is invalid",
                provider_diagnostics=diagnostics,
            ) from exc
        except MetaHTTPError as exc:
            raise self._mapped_error(exc, operation=operation) from exc

        if container_status == "IN_PROGRESS":
            raise TemporaryPublishingError(
                f"{code_prefix}_processing",
                f"Instagram {media_label} is still being processed",
                provider_diagnostics=diagnostics,
            )
        if container_status == "ERROR":
            raise PublishingActionRequired(
                f"{code_prefix}_processing_failed",
                f"Instagram could not process the {media_label} asset",
                provider_diagnostics=diagnostics,
            )
        if container_status == "EXPIRED":
            raise PublishingActionRequired(
                f"{code_prefix}_container_expired",
                f"Instagram {media_label} container expired before publication",
                provider_diagnostics=diagnostics,
            )
        if container_status == "PUBLISHED":
            raise PublishingResultUnknown(
                f"{code_prefix}_already_published_unknown",
                "Publishing outcome requires manual verification",
                provider_diagnostics=diagnostics,
            )
        if container_status != "FINISHED":
            raise PublishingActionRequired(
                f"{code_prefix}_status_unrecognized",
                f"Instagram {media_label} processing status requires attention",
                provider_diagnostics=diagnostics,
            )

    @staticmethod
    def _validate_request(request: InstagramPublishRequest) -> None:
        if request.format == "single_image":
            if len(request.asset_storage_keys) != 1 or len(request.asset_urls) != 1:
                raise PublishingValidationError(
                    "instagram_single_image_assets_invalid",
                    "Single-image publication requires exactly one final image",
                )

        elif request.format == "carousel":
            asset_count = len(request.asset_storage_keys)

            if (
                asset_count < 2
                or asset_count > 10
                or len(request.asset_urls) != asset_count
            ):
                raise PublishingValidationError(
                    "instagram_carousel_assets_invalid",
                    "Instagram carousel requires between 2 and 10 final images",
                )

            if (
                request.existing_child_container_ids
                and len(request.existing_child_container_ids) != asset_count
            ):
                raise PublishingActionRequired(
                    "instagram_carousel_persisted_state_invalid",
                    "Instagram carousel state requires attention",
                )

        elif request.format == "reel":
            if len(request.asset_storage_keys) != 1 or len(request.asset_urls) != 1:
                raise PublishingValidationError(
                    "instagram_reel_assets_invalid",
                    "Instagram Reel publication requires exactly one final video",
                )

        elif request.format == "story":
            if (
                len(request.asset_storage_keys) != 1
                or len(request.asset_urls) != 1
                or len(request.asset_media_types) != 1
            ):
                raise PublishingValidationError(
                    "instagram_story_assets_invalid",
                    "Instagram Story publication requires exactly one final asset",
                )

            if request.asset_media_types[0] not in {"image/jpeg", "video/mp4"}:
                raise PublishingValidationError(
                    "instagram_story_type_unsupported",
                    "Instagram Story publication requires a JPEG image or MP4 video",
                )

        else:
            raise PublishingValidationError(
                "unsupported_instagram_format",
                "Instagram format is not supported for real publishing",
            )

        if not request.professional_account_id or not request.access_token:
            raise PublishingActionRequired(
                "instagram_publish_configuration_missing",
                "Instagram publishing configuration requires attention",
            )

    def _create_carousel_container(self, request: InstagramPublishRequest) -> str:
        assert request.professional_account_id is not None
        assert request.access_token is not None
        children = list(
            request.existing_child_container_ids
            or (None,) * len(request.asset_storage_keys)
        )
        for position, child_id in enumerate(children):
            if child_id:
                continue
            child_id = self.client.create_carousel_image_container(
                account_id=request.professional_account_id,
                image_url=request.asset_urls[position],
                access_token=request.access_token,
            )
            children[position] = child_id
            if request.progress:
                request.progress.carousel_child_created(position, child_id)

        if any(child_id is None for child_id in children):
            raise PublishingActionRequired(
                "instagram_carousel_children_incomplete",
                "Instagram carousel state requires attention",
            )
        for position, child_id in enumerate(children):
            if child_id is None:
                continue
            self._require_container_finished(
                request,
                container_id=child_id,
                code_prefix="instagram_carousel_child",
                media_label="carousel item",
                operation="carousel_child_status",
                position=position,
            )
        return self.client.create_carousel_container(
            account_id=request.professional_account_id,
            children=tuple(child_id for child_id in children if child_id is not None),
            caption=request.caption,
            access_token=request.access_token,
        )

    def publish(self, request: InstagramPublishRequest) -> InstagramPublishResult:
        self._validate_request(request)
        assert request.professional_account_id is not None
        assert request.access_token is not None

        container_id = request.existing_container_id

        if not container_id:
            try:
                if request.format == "single_image":
                    container_id = self.client.create_image_container(
                        account_id=request.professional_account_id,
                        image_url=request.asset_urls[0],
                        caption=request.caption,
                        access_token=request.access_token,
                    )

                elif request.format == "reel":
                    container_id = self.client.create_reel_container(
                        account_id=request.professional_account_id,
                        video_url=request.asset_urls[0],
                        caption=request.caption,
                        access_token=request.access_token,
                    )

                elif request.format == "story":
                    if request.asset_media_types[0] == "video/mp4":
                        container_id = self.client.create_story_video_container(
                            account_id=request.professional_account_id,
                            video_url=request.asset_urls[0],
                            access_token=request.access_token,
                        )
                    else:
                        container_id = self.client.create_story_image_container(
                            account_id=request.professional_account_id,
                            image_url=request.asset_urls[0],
                            access_token=request.access_token,
                        )

                else:
                    container_id = self._create_carousel_container(request)

            except (requests.ConnectTimeout, requests.ReadTimeout) as exc:
                raise TemporaryPublishingError(
                    "instagram_container_timeout",
                    "Instagram container creation timed out",
                ) from exc

            except requests.RequestException as exc:
                raise TemporaryPublishingError(
                    "instagram_container_network",
                    "Instagram is temporarily unavailable",
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

        story_video = (
            request.format == "story"
            and bool(request.asset_media_types)
            and request.asset_media_types[0] == "video/mp4"
        )
        asynchronous_video = request.format == "reel" or story_video

        if request.format == "carousel" and not media_id:
            self._require_container_finished(
                request,
                container_id=container_id,
                code_prefix="instagram_carousel_parent",
                media_label="carousel",
                operation="carousel_parent_status",
            )

        if asynchronous_video and not media_id:
            is_reel = request.format == "reel"
            self._require_container_finished(
                request,
                container_id=container_id,
                code_prefix="instagram_reel" if is_reel else "instagram_story_video",
                media_label="Reel" if is_reel else "Story video",
                operation="container_status",
            )

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
                    container_id,
                    request.access_token,
                )

                raise PublishingResultUnknown(
                    "instagram_publish_timeout_unknown"
                    + (f"_{inspected.lower()}" if inspected else ""),
                    "Publishing outcome requires manual verification",
                ) from exc

            except requests.RequestException as exc:
                inspected = self.client.inspect_container_best_effort(
                    container_id,
                    request.access_token,
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
                        provider_diagnostics=self._safe_provider_diagnostics(
                            exc,
                            operation="media_publish",
                        ),
                    ) from exc

                if exc.retryable:
                    inspected = self.client.inspect_container_best_effort(
                        container_id,
                        request.access_token,
                    )

                    raise PublishingResultUnknown(
                        "instagram_publish_provider_unknown"
                        + (f"_{inspected.lower()}" if inspected else ""),
                        "Publishing outcome requires manual verification",
                    ) from exc

                raise self._mapped_error(exc, operation="media_publish") from exc

            if request.progress:
                request.progress.media_published(media_id)

        permalink: str | None = None

        try:
            permalink = self.client.get_permalink(
                media_id,
                request.access_token,
            )

        except (MetaHTTPError, requests.RequestException, ValueError):
            # Publication already succeeded; permalink enrichment is best effort.
            pass

        metadata = {
            "mode": "meta",
            "format": request.format,
            "permalink_available": str(bool(permalink)).lower(),
        }

        if request.format == "carousel":
            metadata["carousel_asset_count"] = str(
                len(request.asset_storage_keys)
            )
        elif request.format == "story":
            metadata["story_media_type"] = request.asset_media_types[0]

        return InstagramPublishResult(
            container_id=container_id,
            media_id=media_id,
            permalink=permalink,
            provider_status="published_meta",
            metadata=metadata,
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
