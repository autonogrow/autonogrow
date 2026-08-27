from __future__ import annotations

import argparse
import hashlib
import json
import logging
import signal
import socket
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.audit import record_audit
from app.core.config import Settings, get_backend_dir, get_settings
from app.core.database import SessionLocal, engine
from app.core.migration_state import inspect_database_migration_state
from app.models import (
    BusinessChannelIntegration,
    InstagramContent,
    InstagramContentVersion,
    InstagramPublishJob,
)
from app.services.instagram_asset_url_service import (
    SignedAssetURLInvalid,
    build_signed_asset_url,
    resolve_private_asset_path,
)
from app.services.instagram_image_validation import (
    validate_instagram_caption,
    validate_instagram_image,
    validate_instagram_story_image,
)
from app.services.instagram_login_provider import INSTAGRAM_CONTENT_PUBLISH_SCOPE
from app.services.instagram_publish_service import (
    _clear_claim,
    claim_publish_jobs,
    publication_preflight,
    retry_delay_seconds,
    utc_now,
)
from app.services.instagram_publishing_adapter import (
    InstagramPublishingAdapter,
    InstagramPublishingError,
    InstagramPublishRequest,
    InstagramPublishResult,
    PermanentPublishingError,
    PublishingActionRequired,
    PublishingAuthenticationError,
    PublishingResultUnknown,
    PublishingValidationError,
    TemporaryPublishingError,
    get_instagram_publishing_adapter,
)
from app.services.integration_crypto_service import IntegrationCryptoError, decrypt_secret

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedPublish:
    request: InstagramPublishRequest
    business_id: int
    content_id: int


class _PublishProgress:
    def __init__(self, worker: InstagramPublishWorker, job_id: int) -> None:
        self.worker = worker
        self.job_id = job_id

    def carousel_child_created(
        self,
        position: int,
        container_id: str,
    ) -> None:
        self.worker._persist_carousel_child(
            self.job_id,
            position,
            container_id,
        )

    def container_created(self, container_id: str) -> None:
        self.worker._persist_container(self.job_id, container_id)

    def media_published(self, media_id: str) -> None:
        self.worker._persist_media(self.job_id, media_id)

    def publishing_started(self) -> None:
        self.worker._persist_publish_started(self.job_id)


class InstagramPublishWorker:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_factory: sessionmaker[Session] = SessionLocal,
        adapter: InstagramPublishingAdapter | None = None,
        worker_id: str | None = None,
        sleep=time.sleep,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory
        self.adapter = adapter or get_instagram_publishing_adapter(self.settings)
        self.worker_id = (
            worker_id or f"instagram-publisher:{socket.gethostname()}:{uuid4().hex[:10]}"
        )
        self.sleep = sleep
        self._stop_requested = False

    def request_stop(self, *_args: object) -> None:
        self._stop_requested = True

    def _claim(self) -> list[int]:
        with self.session_factory() as db:
            jobs = claim_publish_jobs(
                db,
                worker_id=self.worker_id,
                limit=10,
                claim_ttl_seconds=self.settings.instagram_publishing_claim_ttl_seconds,
            )
            ids = [job.id for job in jobs]
            db.commit()
            return ids

    @staticmethod
    def _scopes(raw: str | None) -> set[str]:
        try:
            parsed = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return set()
        if not isinstance(parsed, list):
            return set()
        return {item for item in parsed if isinstance(item, str)}

    def _uploads_root(self) -> Path:
        configured = self.settings.uploads_dir.strip()
        root = Path(configured) if configured else get_backend_dir() / "uploads"
        return (root if root.is_absolute() else get_backend_dir() / root).resolve()

    @staticmethod
    def _block_job(
        db: Session,
        job: InstagramPublishJob,
        error: InstagramPublishingError,
        *,
        audit_action: str | None = None,
    ) -> None:
        validation_failure = isinstance(error, PublishingValidationError)
        job.status = "failed" if validation_failure else "action_required"
        job.provider_status = (
            "validation_failure" if validation_failure else "prerequisites_action_required"
        )
        job.provider_error_code = error.code
        job.safe_error_message = error.safe_message[:500]
        _clear_claim(job)
        record_audit(
            db,
            action=(
                audit_action
                or (
                    "publish_validation_failed" if validation_failure else "publish_action_required"
                )
            ),
            business_id=job.business_id,
            resource_type="instagram_publish_job",
            resource_id=job.id,
            metadata={
                "content_id": job.content_item_id,
                "version_id": job.content_version_id,
                "reason": error.code,
            },
            commit=False,
        )

    def _validate_mp4_asset(
        self,
        asset,
        path: Path,
        *,
        code_prefix: str,
        media_label: str,
    ) -> dict[str, str]:
        if asset.media_type != "video/mp4":
            raise PublishingValidationError(
                f"{code_prefix}_type_unsupported",
                f"Instagram {media_label} publication requires an MP4 video",
            )

        if not path.is_file():
            raise PublishingValidationError(
                f"{code_prefix}_file_missing",
                f"Instagram {media_label} video file is unavailable",
            )

        try:
            size_bytes = path.stat().st_size
        except OSError as exc:
            raise PublishingValidationError(
                f"{code_prefix}_file_unavailable",
                f"Instagram {media_label} video file is unavailable",
            ) from exc

        max_bytes = self.settings.instagram_video_upload_max_size_mb * 1024 * 1024

        if size_bytes <= 0 or size_bytes > max_bytes:
            raise PublishingValidationError(
                f"{code_prefix}_size_invalid",
                f"Instagram {media_label} video does not meet the configured size limit",
            )

        if asset.size_bytes != size_bytes:
            raise PublishingValidationError(
                f"{code_prefix}_size_mismatch",
                f"Instagram {media_label} video integrity check failed",
            )

        digest = hashlib.sha256()

        try:
            with path.open("rb") as stream:
                header = stream.read(12)

                if len(header) < 12 or header[4:8] != b"ftyp":
                    raise PublishingValidationError(
                        f"{code_prefix}_content_invalid",
                        f"Instagram {media_label} asset is not a valid MP4 container",
                    )

                digest.update(header)

                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)

        except PublishingValidationError:
            raise
        except OSError as exc:
            raise PublishingValidationError(
                f"{code_prefix}_file_unavailable",
                f"Instagram {media_label} video file is unavailable",
            ) from exc

        sha256 = digest.hexdigest()

        if not asset.sha256 or asset.sha256 != sha256:
            raise PublishingValidationError(
                f"{code_prefix}_hash_mismatch",
                f"Instagram {media_label} video integrity check failed",
            )

        return {
            "asset_sha256": sha256,
            "video_size_bytes": str(size_bytes),
            "video_media_type": asset.media_type,
        }

    def _validate_reel_asset(self, asset, path: Path) -> dict[str, str]:
        return self._validate_mp4_asset(
            asset,
            path,
            code_prefix="instagram_reel",
            media_label="Reel",
        )

    def _validate_story_video_asset(self, asset, path: Path) -> dict[str, str]:
        return self._validate_mp4_asset(
            asset,
            path,
            code_prefix="instagram_story_video",
            media_label="Story",
        )

    def _meta_request_fields(self, job, version, integration, links):
        if version.format == "single_image":
            if len(links) != 1:
                raise PublishingValidationError(
                    "instagram_single_image_assets_invalid",
                    "Single-image publication requires exactly one final image",
                )
        elif version.format == "carousel":
            if len(links) < 2 or len(links) > 10:
                raise PublishingValidationError(
                    "instagram_carousel_assets_invalid",
                    "Instagram carousel requires between 2 and 10 final images",
                )
        elif version.format == "reel":
            if len(links) != 1:
                raise PublishingValidationError(
                    "instagram_reel_assets_invalid",
                    "Instagram Reel publication requires exactly one final video",
                )
        elif version.format == "story":
            if len(links) != 1:
                raise PublishingValidationError(
                    "instagram_story_assets_invalid",
                    "Instagram Story publication requires exactly one final asset",
                )
            if links[0].asset.media_type not in {"image/jpeg", "video/mp4"}:
                raise PublishingValidationError(
                    "instagram_story_type_unsupported",
                    "Instagram Story publication requires a JPEG image or MP4 video",
                )
        else:
            raise PublishingValidationError(
                "unsupported_instagram_format",
                "Instagram format is not supported for real publishing",
            )

        if not integration.encrypted_access_token or not integration.encryption_key_version:
            raise PublishingAuthenticationError(
                "instagram_credentials_missing",
                "Instagram needs to be reconnected",
            )

        if INSTAGRAM_CONTENT_PUBLISH_SCOPE not in self._scopes(
            integration.granted_scopes_json
        ):
            raise PublishingActionRequired(
                "instagram_publish_scope_missing",
                "Instagram publishing permission is missing; reconnect the account",
            )

        account_id = integration.external_account_id.strip()

        if not account_id:
            raise PublishingActionRequired(
                "instagram_professional_account_missing",
                "Instagram professional account identifier is missing",
            )

        try:
            access_token = decrypt_secret(
                integration.encrypted_access_token,
                integration.encryption_key_version,
                settings=self.settings,
            )
        except IntegrationCryptoError as exc:
            raise PublishingAuthenticationError(
                "instagram_credentials_unavailable",
                "Instagram needs to be reconnected",
            ) from exc

        validate_instagram_caption(version.caption)

        asset_urls: list[str] = []
        images = []
        video_metadata: dict[str, str] | None = None

        for link in links:
            asset = link.asset
            path = resolve_private_asset_path(
                asset.storage_key,
                root=self._uploads_root(),
            )

            if version.format == "reel":
                video_metadata = self._validate_reel_asset(asset, path)
            elif version.format == "story" and asset.media_type == "video/mp4":
                video_metadata = self._validate_story_video_asset(asset, path)
            elif version.format == "story":
                image = validate_instagram_story_image(asset, path)
                images.append(image)
            else:
                image = validate_instagram_image(asset, path)
                images.append(image)

            try:
                asset_url = build_signed_asset_url(
                    self.settings,
                    business_id=job.business_id,
                    version_id=job.content_version_id,
                    asset_id=asset.id,
                )
            except SignedAssetURLInvalid as exc:
                raise PublishingActionRequired(
                    "instagram_asset_delivery_unavailable",
                    "Secure Instagram asset delivery is not configured",
                ) from exc

            asset_urls.append(asset_url)

        if version.format == "single_image":
            image = images[0]
            metadata = {
                "asset_sha256": image.sha256,
                "image_width": str(image.width),
                "image_height": str(image.height),
            }
        elif version.format == "carousel":
            metadata = {
                "carousel_asset_count": str(len(images)),
                "carousel_asset_sha256s": json.dumps(
                    [image.sha256 for image in images],
                    separators=(",", ":"),
                ),
                "carousel_image_dimensions": json.dumps(
                    [
                        [image.width, image.height]
                        for image in images
                    ],
                    separators=(",", ":"),
                ),
            }
        elif version.format == "story" and links[0].asset.media_type == "image/jpeg":
            image = images[0]
            metadata = {
                "asset_sha256": image.sha256,
                "image_width": str(image.width),
                "image_height": str(image.height),
                "story_media_type": "image/jpeg",
            }
        else:
            metadata = video_metadata or {}
            if version.format == "story":
                metadata["story_media_type"] = links[0].asset.media_type

        return account_id, access_token, tuple(asset_urls), metadata

    def _prepare(self, job_id: int) -> PreparedPublish | None:
        with self.session_factory() as db:
            job = (
                db.query(InstagramPublishJob)
                .filter(InstagramPublishJob.id == job_id)
                .with_for_update()
                .first()
            )
            if job is None or job.status != "claimed" or job.claimed_by != self.worker_id:
                return None
            content = db.get(InstagramContent, job.content_item_id)
            version = db.get(InstagramContentVersion, job.content_version_id)
            preflight_error: PublishingActionRequired | None
            if content is None or version is None:
                preflight_error = PublishingActionRequired(
                    "publish_version_is_not_current", "Publishing version is unavailable"
                )
                integration = None
            else:
                preflight = publication_preflight(
                    db,
                    content,
                    version=version,
                    settings=self.settings,
                    validate_files=self.settings.instagram_publishing_mode == "meta",
                    publication_at=utc_now(),
                )
                integration = preflight.integration
                preflight_error = (
                    PublishingActionRequired(
                        preflight.code or "publish_preflight_failed",
                        preflight.safe_message or "Publishing prerequisites require attention",
                    )
                    if not preflight.ok
                    else None
                )
            if preflight_error is None and content is not None and content.status != "scheduled":
                preflight_error = PublishingActionRequired(
                    "publish_content_is_not_scheduled", "Content is no longer scheduled"
                )
            if preflight_error is None and (
                integration is None or integration.id != job.integration_id
            ):
                preflight_error = PublishingActionRequired(
                    "publish_integration_changed", "Instagram integration changed"
                )
            if preflight_error is not None:
                self._block_job(
                    db,
                    job,
                    preflight_error,
                    audit_action=(
                        "integration_blocked_publish"
                        if "integration" in preflight_error.code
                        else None
                    ),
                )
                db.commit()
                return None
            content = cast(InstagramContent, content)
            version = cast(InstagramContentVersion, version)
            integration = cast(BusinessChannelIntegration, integration)
            links = sorted(version.asset_links, key=lambda item: item.position)
            account_id = access_token = None
            asset_urls: tuple[str, ...] = ()
            metadata: dict[str, str] = {}

            if self.settings.instagram_publishing_mode == "meta":
                try:
                    (
                        account_id,
                        access_token,
                        asset_urls,
                        metadata,
                    ) = self._meta_request_fields(
                        job,
                        version,
                        integration,
                        links,
                    )

                except InstagramPublishingError as exc:
                    self._block_job(db, job, exc)
                    db.commit()
                    return None

            existing_child_container_ids: tuple[str | None, ...] = ()

            if version.format == "carousel":
                try:
                    previous_metadata = json.loads(
                        job.provider_metadata_json or "{}"
                    )
                except (TypeError, ValueError):
                    previous_metadata = {}

                if not isinstance(previous_metadata, dict):
                    previous_metadata = {}

                raw_children = previous_metadata.get(
                    "carousel_child_container_ids"
                )

                if isinstance(raw_children, list):
                    normalized_children = [
                        value if isinstance(value, str) and value else None
                        for value in raw_children[: len(links)]
                    ]

                    while len(normalized_children) < len(links):
                        normalized_children.append(None)

                    existing_child_container_ids = tuple(
                        normalized_children
                    )

            request = InstagramPublishRequest(
                idempotency_key=job.idempotency_key,
                business_id=job.business_id,
                content_id=job.content_item_id,
                version_id=job.content_version_id,
                caption=version.caption,
                format=version.format,
                asset_storage_keys=tuple(link.asset.storage_key for link in links),
                asset_media_types=tuple(link.asset.media_type for link in links),
                professional_account_id=account_id,
                access_token=access_token,
                asset_urls=asset_urls,
                existing_child_container_ids=existing_child_container_ids,
                existing_container_id=job.provider_container_id,
                existing_media_id=job.provider_media_id,
                progress=_PublishProgress(self, job.id),
            )
            if self.settings.instagram_publishing_mode == "meta":
                job.status = "publishing" if job.provider_container_id else "creating_container"
                job.provider_status = job.status
                try:
                    previous_metadata = json.loads(
                        job.provider_metadata_json or "{}"
                    )
                except (TypeError, ValueError):
                    previous_metadata = {}

                if not isinstance(previous_metadata, dict):
                    previous_metadata = {}

                job.provider_metadata_json = json.dumps(
                    {
                        **previous_metadata,
                        **metadata,
                    },
                    sort_keys=True,
                )
            else:
                job.status = "simulating_publish"
                job.provider_status = "simulating_publish"
            record_audit(
                db,
                action="publish_attempt_started",
                business_id=job.business_id,
                resource_type="instagram_publish_job",
                resource_id=job.id,
                metadata={
                    "content_id": job.content_item_id,
                    "version_id": job.content_version_id,
                    "attempt": job.attempt_count,
                    "worker_id": self.worker_id,
                    "mode": self.settings.instagram_publishing_mode,
                },
                commit=False,
            )
            db.commit()
            return PreparedPublish(request, job.business_id, job.content_item_id)

    def _authorize_provider_call(self, job_id: int) -> bool:
        with self.session_factory() as db:
            seed = db.get(InstagramPublishJob, job_id)
            if seed is None:
                return False
            content = (
                db.query(InstagramContent)
                .filter(InstagramContent.id == seed.content_item_id)
                .with_for_update()
                .first()
            )
            job = (
                db.query(InstagramPublishJob)
                .filter(InstagramPublishJob.id == job_id)
                .with_for_update()
                .first()
            )
            if (
                content is None
                or job is None
                or job.claimed_by != self.worker_id
                or job.status
                not in {"simulating_publish", "creating_container", "publishing"}
            ):
                return False
            version = db.get(InstagramContentVersion, job.content_version_id)
            preflight = (
                publication_preflight(
                    db,
                    content,
                    version=version,
                    settings=self.settings,
                    validate_files=self.settings.instagram_publishing_mode == "meta",
                    publication_at=utc_now(),
                )
                if version is not None
                else None
            )
            if content.status != "scheduled" or preflight is None or not preflight.ok:
                error = PublishingActionRequired(
                    (preflight.code or "publish_preflight_failed")
                    if preflight
                    else "publish_version_is_not_current",
                    (preflight.safe_message or "Publication is not allowed")
                    if preflight
                    else "Publishing version is unavailable",
                )
                self._block_job(db, job, error)
                db.commit()
                return False
            job.provider_status = "provider_call_authorized"
            record_audit(
                db,
                action="publish_provider_call_authorized",
                business_id=job.business_id,
                resource_type="instagram_publish_job",
                resource_id=job.id,
                metadata={
                    "content_id": job.content_item_id,
                    "version_id": job.content_version_id,
                    "worker_id": self.worker_id,
                },
                commit=False,
            )
            db.commit()
            return True

    def _persist_carousel_child(
        self,
        job_id: int,
        position: int,
        container_id: str,
    ) -> None:
        if position < 0 or position > 9:
            raise PublishingActionRequired(
                "instagram_carousel_position_invalid",
                "Instagram carousel state requires attention",
            )

        if not container_id or len(container_id) > 255:
            raise PublishingActionRequired(
                "instagram_carousel_child_invalid",
                "Instagram carousel state requires attention",
            )

        with self.session_factory() as db:
            job = (
                db.query(InstagramPublishJob)
                .filter_by(id=job_id)
                .with_for_update()
                .first()
            )

            if (
                job is None
                or job.status != "creating_container"
                or job.claimed_by != self.worker_id
            ):
                raise PublishingActionRequired(
                    "publish_job_changed_during_carousel_creation",
                    "Publishing job changed while creating the carousel",
                )

            try:
                metadata = json.loads(
                    job.provider_metadata_json or "{}"
                )
            except (TypeError, ValueError):
                metadata = {}

            if not isinstance(metadata, dict):
                metadata = {}

            raw_children = metadata.get(
                "carousel_child_container_ids"
            )

            if isinstance(raw_children, list):
                children = list(raw_children)
            else:
                children = []

            while len(children) <= position:
                children.append(None)

            existing = children[position]

            if (
                existing is not None
                and existing != container_id
            ):
                raise PublishingActionRequired(
                    "instagram_carousel_child_conflict",
                    "Instagram carousel state requires attention",
                )

            children[position] = container_id

            metadata["carousel_child_container_ids"] = children

            job.provider_metadata_json = json.dumps(
                metadata,
                sort_keys=True,
            )
            job.provider_status = "carousel_child_created"

            record_audit(
                db,
                action="publish_carousel_child_created",
                business_id=job.business_id,
                resource_type="instagram_publish_job",
                resource_id=job.id,
                metadata={
                    "content_id": job.content_item_id,
                    "version_id": job.content_version_id,
                    "position": position,
                    "provider_container_id": container_id,
                },
                commit=False,
            )

            db.commit()

    def _persist_container(self, job_id: int, container_id: str) -> None:
        with self.session_factory() as db:
            job = db.query(InstagramPublishJob).filter_by(id=job_id).with_for_update().first()
            if (
                job is None
                or job.status != "creating_container"
                or job.claimed_by != self.worker_id
            ):
                raise PublishingActionRequired(
                    "publish_job_changed_during_container_creation",
                    "Publishing job changed while creating the container",
                )
            job.provider_container_id = container_id[:255]
            job.status = "publishing"
            job.provider_status = "container_created"
            record_audit(
                db,
                action="publish_container_created",
                business_id=job.business_id,
                resource_type="instagram_publish_job",
                resource_id=job.id,
                metadata={
                    "content_id": job.content_item_id,
                    "version_id": job.content_version_id,
                    "provider_container_id": container_id[:255],
                },
                commit=False,
            )
            db.commit()

    def _persist_media(self, job_id: int, media_id: str) -> None:
        with self.session_factory() as db:
            job = db.query(InstagramPublishJob).filter_by(id=job_id).with_for_update().first()
            if job is None or job.status != "publishing" or job.claimed_by != self.worker_id:
                raise PublishingResultUnknown(
                    "publish_job_changed_after_provider_publish",
                    "Publishing outcome requires manual verification",
                )
            job.provider_media_id = media_id[:255]
            job.provider_status = "media_id_persisted"
            record_audit(
                db,
                action="publish_media_id_persisted",
                business_id=job.business_id,
                resource_type="instagram_publish_job",
                resource_id=job.id,
                metadata={
                    "content_id": job.content_item_id,
                    "version_id": job.content_version_id,
                    "provider_media_id": media_id[:255],
                },
                commit=False,
            )
            db.commit()

    def _persist_publish_started(self, job_id: int) -> None:
        with self.session_factory() as db:
            seed = db.get(InstagramPublishJob, job_id)
            if seed is None:
                raise PublishingActionRequired(
                    "publish_job_changed_before_provider_publish",
                    "Publishing job changed before provider publication",
                )
            content = (
                db.query(InstagramContent)
                .filter(InstagramContent.id == seed.content_item_id)
                .with_for_update()
                .first()
            )
            job = db.query(InstagramPublishJob).filter_by(id=job_id).with_for_update().first()
            if (
                content is None
                or job is None
                or job.status != "publishing"
                or job.claimed_by != self.worker_id
            ):
                raise PublishingActionRequired(
                    "publish_job_changed_before_provider_publish",
                    "Publishing job changed before provider publication",
                )
            version = db.get(InstagramContentVersion, job.content_version_id)
            preflight = (
                publication_preflight(
                    db,
                    content,
                    version=version,
                    settings=self.settings,
                    validate_files=self.settings.instagram_publishing_mode == "meta",
                    publication_at=utc_now(),
                )
                if version is not None
                else None
            )
            if content.status != "scheduled" or preflight is None or not preflight.ok:
                error = PublishingActionRequired(
                    (preflight.code or "publish_preflight_failed")
                    if preflight
                    else "publish_version_is_not_current",
                    (preflight.safe_message or "Publication is not allowed")
                    if preflight
                    else "Publishing version is unavailable",
                )
                self._block_job(db, job, error)
                db.commit()
                raise error
            job.provider_status = "media_publish_started"
            record_audit(
                db,
                action="publish_provider_call_started",
                business_id=job.business_id,
                resource_type="instagram_publish_job",
                resource_id=job.id,
                metadata={
                    "content_id": job.content_item_id,
                    "version_id": job.content_version_id,
                    "attempt": job.attempt_count,
                },
                commit=False,
            )
            db.commit()

    def _finish_success(self, job_id: int, result: InstagramPublishResult) -> None:
        with self.session_factory() as db:
            job = db.query(InstagramPublishJob).filter_by(id=job_id).with_for_update().first()
            normal_completion = bool(
                job is not None
                and job.status in {"simulating_publish", "publishing"}
                and job.claimed_by == self.worker_id
            )
            known_completion_after_hold = bool(
                job is not None
                and job.status == "action_required"
                and job.provider_status == "outcome_requires_review"
            )
            if job is None or not (normal_completion or known_completion_after_hold):
                return
            job.status = "published"
            job.provider_container_id = result.container_id
            job.provider_media_id = result.media_id
            job.provider_permalink = result.permalink
            job.provider_status = result.provider_status
            job.provider_error_code = None
            job.safe_error_message = None
            try:
                previous = json.loads(
                    job.provider_metadata_json or "{}"
                )
            except (TypeError, ValueError):
                previous = {}

            if not isinstance(previous, dict):
                previous = {}

            job.provider_metadata_json = json.dumps(
                {
                    **previous,
                    **(result.metadata or {}),
                },
                sort_keys=True,
            )
            job.published_at = utc_now()
            _clear_claim(job)
            content = db.get(InstagramContent, job.content_item_id)
            if content is not None and content.business_id == job.business_id:
                content.status = "published"
            record_audit(
                db,
                action="publish_succeeded",
                business_id=job.business_id,
                resource_type="instagram_publish_job",
                resource_id=job.id,
                metadata={
                    "content_id": job.content_item_id,
                    "version_id": job.content_version_id,
                    "provider_media_id": result.media_id,
                    "attempt": job.attempt_count,
                    "completed_after_publication_hold": known_completion_after_hold,
                },
                commit=False,
            )
            db.commit()

    def _finish_error(self, job_id: int, exc: Exception) -> None:
        with self.session_factory() as db:
            job = db.query(InstagramPublishJob).filter_by(id=job_id).with_for_update().first()
            if (
                job is None
                or job.status not in {"simulating_publish", "creating_container", "publishing"}
                or job.claimed_by != self.worker_id
            ):
                return
            action = "publish_failed"
            if isinstance(exc, PublishingResultUnknown):
                job.status = "action_required"
                job.provider_status = "unknown_result"
                code, message = exc.code, exc.safe_message
                action = "publish_action_required"
            elif isinstance(exc, (PublishingAuthenticationError, PublishingActionRequired)):
                job.status = "action_required"
                job.provider_status = "action_required"
                code, message = exc.code, exc.safe_message
                action = "publish_action_required"
            elif isinstance(exc, PermanentPublishingError):
                job.status = "failed"
                job.provider_status = (
                    "validation_failure"
                    if isinstance(exc, PublishingValidationError)
                    else "permanent_failure"
                )
                code, message = exc.code, exc.safe_message
            else:
                if isinstance(exc, TemporaryPublishingError):
                    code, message = exc.code, exc.safe_message
                elif isinstance(exc, TimeoutError):
                    code, message = "simulated_timeout", "Simulated provider timed out"
                else:
                    code, message = "unexpected_publish_error", "Publishing failed safely"
                if job.attempt_count < job.max_attempts:
                    job.status = "retry_wait"
                    job.provider_status = "temporary_failure"
                    job.next_attempt_at = utc_now() + timedelta(
                        seconds=retry_delay_seconds(job, self.settings)
                    )
                    action = "publish_retry_scheduled"
                else:
                    job.status = "failed"
                    job.provider_status = "attempts_exhausted"
            job.provider_error_code = code
            job.safe_error_message = message[:500]
            if isinstance(exc, InstagramPublishingError) and exc.provider_diagnostics:
                try:
                    provider_metadata = json.loads(job.provider_metadata_json or "{}")
                except (TypeError, ValueError):
                    provider_metadata = {}
                if not isinstance(provider_metadata, dict):
                    provider_metadata = {}
                provider_metadata["last_provider_error"] = {
                    key: value
                    for key, value in exc.provider_diagnostics.items()
                    if key
                    in {
                        "operation",
                        "http_status",
                        "error_code",
                        "error_subcode",
                        "error_type",
                        "is_transient",
                        "trace_id",
                        "container_status",
                        "carousel_position",
                    }
                    and value is not None
                }
                job.provider_metadata_json = json.dumps(
                    provider_metadata,
                    sort_keys=True,
                )
            _clear_claim(job)
            record_audit(
                db,
                action=action,
                business_id=job.business_id,
                resource_type="instagram_publish_job",
                resource_id=job.id,
                metadata={
                    "content_id": job.content_item_id,
                    "version_id": job.content_version_id,
                    "error_code": code,
                    "attempt": job.attempt_count,
                },
                commit=False,
            )
            db.commit()

    def process_job(self, job_id: int) -> None:
        prepared = self._prepare(job_id)
        if prepared is None or not self._authorize_provider_call(job_id):
            return
        try:
            result = self.adapter.publish(prepared.request)
        except Exception as exc:
            if isinstance(exc, InstagramPublishingError):
                diagnostics = exc.provider_diagnostics
                logger.warning(
                    "instagram_publish_failed job_id=%s worker_id=%s error_type=%s "
                    "safe_code=%s provider_operation=%s provider_http_status=%s "
                    "provider_error_subcode=%s provider_is_transient=%s",
                    job_id,
                    self.worker_id,
                    type(exc).__name__,
                    exc.code,
                    diagnostics.get("operation") or "unavailable",
                    diagnostics.get("http_status") or "unavailable",
                    diagnostics.get("error_subcode") or "unavailable",
                    diagnostics.get("is_transient")
                    if diagnostics.get("is_transient") is not None
                    else "unavailable",
                )
            else:
                logger.warning(
                    "instagram_publish_failed job_id=%s worker_id=%s error_type=%s",
                    job_id,
                    self.worker_id,
                    type(exc).__name__,
                )
            self._finish_error(job_id, exc)
            return
        self._finish_success(job_id, result)
        logger.info("instagram_publish_succeeded job_id=%s worker_id=%s", job_id, self.worker_id)

    def run_once(self) -> int:
        if not self.settings.instagram_publishing_worker_enabled:
            return 0
        ids = self._claim()
        for job_id in ids:
            if self._stop_requested:
                break
            self.process_job(job_id)
        return len(ids)

    def run_forever(self, poll_seconds: float | None = None) -> None:
        interval = poll_seconds or self.settings.instagram_publishing_poll_seconds
        while not self._stop_requested:
            jobs = self.run_once()
            if jobs == 0 and not self._stop_requested:
                self.sleep(interval)


def worker_startup_check(
    settings: Settings,
    *,
    session_factory: sessionmaker[Session] = SessionLocal,
    database_engine: Engine = engine,
) -> dict[str, object]:
    """Validate worker prerequisites without claiming jobs or changing application state."""
    with session_factory() as db:
        db.execute(text("SELECT 1"))
        dialect = db.get_bind().dialect.name
    if settings.app_env in {"staging", "production"}:
        if dialect != "postgresql":
            raise RuntimeError("Instagram publisher requires PostgreSQL in managed environments")
        state = inspect_database_migration_state(database_engine)
        if not state.is_at_head or len(state.head_revisions) != 1:
            raise RuntimeError("Instagram publisher database is not at the single Alembic head")
        __import__("psycopg")
    adapter = get_instagram_publishing_adapter(settings)
    return {
        "ok": True,
        "app_env": settings.app_env,
        "database_dialect": dialect,
        "publishing_mode": settings.instagram_publishing_mode,
        "provider_adapter": type(adapter).__name__,
        "worker_enabled": settings.instagram_publishing_worker_enabled,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Instagram publishing worker")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--once", action="store_true")
    action.add_argument(
        "--check",
        action="store_true",
        help="Valida configuración y DB sin reclamar ni publicar jobs",
    )
    parser.add_argument("--poll-seconds", type=float)
    args = parser.parse_args()
    settings = get_settings()
    if args.check:
        print(json.dumps(worker_startup_check(settings), sort_keys=True))
        return 0
    worker = InstagramPublishWorker(settings=settings)
    signal.signal(signal.SIGTERM, worker.request_stop)
    signal.signal(signal.SIGINT, worker.request_stop)
    if args.once:
        worker.run_once()
    else:
        worker.run_forever(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
