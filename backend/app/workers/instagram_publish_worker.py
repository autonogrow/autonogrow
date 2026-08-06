from __future__ import annotations

import argparse
import json
import logging
import signal
import socket
import time
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.core.audit import record_audit
from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.models import (
    InstagramContent,
    InstagramContentSettings,
    InstagramContentValidation,
    InstagramContentVersion,
    InstagramPublishJob,
)
from app.services.instagram_publish_service import (
    _clear_claim,
    claim_publish_jobs,
    integration_eligibility,
    retry_delay_seconds,
    utc_now,
)
from app.services.instagram_publishing_adapter import (
    InstagramPublishingAdapter,
    InstagramPublishRequest,
    InstagramPublishResult,
    PermanentPublishingError,
    SimulatedInstagramPublishingAdapter,
    TemporaryPublishingError,
    UnknownPublishingResult,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedPublish:
    request: InstagramPublishRequest
    business_id: int
    content_id: int


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
        self.adapter = adapter or SimulatedInstagramPublishingAdapter()
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
            service = db.get(InstagramContentSettings, job.business_id)
            validation = (
                db.query(InstagramContentValidation)
                .filter(
                    InstagramContentValidation.business_id == job.business_id,
                    InstagramContentValidation.content_id == job.content_item_id,
                    InstagramContentValidation.version_id == job.content_version_id,
                    InstagramContentValidation.invalidated_at.is_(None),
                )
                .first()
            )
            latest = (
                db.query(InstagramContentVersion.id)
                .filter(
                    InstagramContentVersion.business_id == job.business_id,
                    InstagramContentVersion.content_id == job.content_item_id,
                )
                .order_by(InstagramContentVersion.version_number.desc())
                .first()
            )
            integration, integration_error = integration_eligibility(db, job.business_id)
            error = None
            if (
                content is None
                or version is None
                or latest is None
                or latest[0] != job.content_version_id
            ):
                error = "publish_version_is_not_current"
            elif content.status != "scheduled":
                error = "publish_content_is_not_scheduled"
            elif service is None or not service.enabled:
                error = "instagram_content_service_disabled"
            elif validation is None:
                error = "publish_validation_revoked"
            elif integration_error or integration is None or integration.id != job.integration_id:
                error = integration_error or "publish_integration_changed"
            elif not version.asset_links:
                error = "publish_assets_missing"
            elif version.format == "single_image" and len(version.asset_links) != 1:
                error = "publish_assets_do_not_match_format"
            elif version.format == "carousel" and len(version.asset_links) < 2:
                error = "publish_assets_do_not_match_format"
            elif any(
                link.asset.business_id != job.business_id
                or link.asset.content_id != job.content_item_id
                for link in version.asset_links
            ):
                error = "publish_asset_scope_mismatch"
            if error:
                job.status = "action_required"
                job.provider_error_code = error
                job.safe_error_message = "Publishing prerequisites require attention"
                _clear_claim(job)
                record_audit(
                    db,
                    action="integration_blocked_publish"
                    if "integration" in error
                    else "publish_action_required",
                    business_id=job.business_id,
                    resource_type="instagram_publish_job",
                    resource_id=job.id,
                    metadata={"reason": error},
                    commit=False,
                )
                db.commit()
                return None
            assert content is not None and version is not None
            links = sorted(version.asset_links, key=lambda item: item.position)
            request = InstagramPublishRequest(
                idempotency_key=job.idempotency_key,
                business_id=job.business_id,
                content_id=job.content_item_id,
                version_id=job.content_version_id,
                caption=version.caption,
                format=version.format,
                asset_storage_keys=tuple(link.asset.storage_key for link in links),
            )
            job.status = "simulating_publish"
            job.provider_status = "simulating_publish"
            record_audit(
                db,
                action="publish_attempt_started",
                business_id=job.business_id,
                resource_type="instagram_publish_job",
                resource_id=job.id,
                metadata={"attempt": job.attempt_count, "worker_id": self.worker_id},
                commit=False,
            )
            db.commit()
            return PreparedPublish(
                request=request, business_id=job.business_id, content_id=job.content_item_id
            )

    def _finish_success(self, job_id: int, result: InstagramPublishResult) -> None:
        with self.session_factory() as db:
            job = (
                db.query(InstagramPublishJob)
                .filter(InstagramPublishJob.id == job_id)
                .with_for_update()
                .first()
            )
            if (
                job is None
                or job.status != "simulating_publish"
                or job.claimed_by != self.worker_id
            ):
                return
            clock = utc_now()
            job.status = "published"
            job.provider_container_id = result.container_id
            job.provider_media_id = result.media_id
            job.provider_permalink = result.permalink
            job.provider_status = result.provider_status
            job.provider_error_code = None
            job.safe_error_message = None
            job.provider_metadata_json = json.dumps(result.metadata or {}, sort_keys=True)
            job.published_at = clock
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
                metadata={"provider_media_id": result.media_id, "attempt": job.attempt_count},
                commit=False,
            )
            db.commit()

    def _finish_error(self, job_id: int, exc: Exception) -> None:
        with self.session_factory() as db:
            job = (
                db.query(InstagramPublishJob)
                .filter(InstagramPublishJob.id == job_id)
                .with_for_update()
                .first()
            )
            if (
                job is None
                or job.status != "simulating_publish"
                or job.claimed_by != self.worker_id
            ):
                return
            action = "publish_failed"
            if isinstance(exc, UnknownPublishingResult):
                job.status = "action_required"
                job.provider_status = "unknown_result"
                code, message = exc.code, exc.safe_message
                action = "publish_action_required"
            elif isinstance(exc, PermanentPublishingError):
                job.status = "failed"
                job.provider_status = "permanent_failure"
                code, message = exc.code, exc.safe_message
            else:
                if isinstance(exc, TemporaryPublishingError):
                    code, message = exc.code, exc.safe_message
                elif isinstance(exc, TimeoutError):
                    code, message = "simulated_timeout", "Simulated provider timed out"
                else:
                    code, message = (
                        "unexpected_simulated_error",
                        "Simulated publishing failed safely",
                    )
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
            _clear_claim(job)
            record_audit(
                db,
                action=action,
                business_id=job.business_id,
                resource_type="instagram_publish_job",
                resource_id=job.id,
                metadata={"error_code": code, "attempt": job.attempt_count},
                commit=False,
            )
            db.commit()

    def process_job(self, job_id: int) -> None:
        prepared = self._prepare(job_id)
        if prepared is None:
            return
        try:
            result = self.adapter.publish(prepared.request)
        except Exception as exc:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulated Instagram publishing worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float)
    args = parser.parse_args()
    settings = get_settings()
    if not settings.instagram_publishing_simulated_mode:
        logger.error("instagram_publish_worker_refuses_non_simulated_mode")
        return 2
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
