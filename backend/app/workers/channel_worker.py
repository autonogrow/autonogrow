import json
import logging
import os
import signal
import socket
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import requests
from sqlalchemy import or_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import Session, sessionmaker

from app.core.audit import record_audit
from app.core.config import Settings, get_settings
from app.core.database import SessionLocal, is_sqlite_locked_error
from app.core.observability import request_id_context
from app.models import (
    Business,
    BusinessChannelIntegration,
    ChannelOutboxMessage,
    ConversationMessage,
    InstagramMediaSyncState,
    MetaIntegrationJob,
    WebhookInboxEvent,
)
from app.services.channel_provider_contracts import (
    ChannelInboxProcessingError,
    ProviderSender,
)
from app.services.channel_provider_service import (
    delivery_supported,
    integration_credentials_expired,
    process_channel_inbox_event,
    provider_senders,
)
from app.services.database_error_service import classify_database_error, report_database_incident
from app.services.inbox_queue_service import claim_inbox_jobs, fail_inbox_job
from app.services.incident_service import report_incident, resolve_related_incidents
from app.services.instagram_media_sync_service import (
    advance_or_finish_sync,
    enqueue_instagram_media_sync,
    mark_media_unavailable,
    mark_probe_available,
    mark_sync_failed,
    mark_sync_started,
    persist_media_page,
    unavailable_probe_candidates,
)
from app.services.instagram_meta_client import (
    InstagramMetaClient,
    InstagramRemoteMediaItem,
    MetaHTTPError,
)
from app.services.integration_crypto_service import IntegrationCryptoError, decrypt_secret
from app.services.maintenance_service import maintenance_enabled
from app.services.meta_integration_health_checkers import health_checker_for_provider
from app.services.meta_integration_health_contracts import (
    IntegrationHealthChecker,
    UnsupportedIntegrationHealthProvider,
)
from app.services.meta_integration_job_service import (
    apply_integration_health_result,
    claim_meta_integration_jobs,
    cleanup_meta_integration_attempts,
    enqueue_meta_integration_job,
    fail_meta_integration_job,
    finish_meta_integration_job,
    integration_health_blocks_delivery,
    schedule_due_meta_jobs,
)
from app.services.outbox_queue_service import claim_outbox_jobs, fail_outbox_job, finish_outbox_job
from app.services.queue_error_service import QueueErrorClassification, classify_queue_error
from app.services.worker_heartbeat_service import update_worker_heartbeat

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedDelivery:
    outbox_id: int
    business_id: int
    integration_id: int
    recipient_id: str
    text: str
    access_token: str
    external_account_id: str
    sender: ProviderSender


@dataclass(frozen=True)
class PreparedMetaHealthJob:
    job_id: int
    business_id: int
    integration_id: int
    job_type: str
    integration: BusinessChannelIntegration
    access_token: str
    checker: IntegrationHealthChecker


class ChannelWorker:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_factory: sessionmaker[Session] = SessionLocal,
        senders: Mapping[str, ProviderSender] | None = None,
        instagram_media_client: InstagramMetaClient | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory
        self.provider_senders = provider_senders(senders)
        self.instagram_media_client = instagram_media_client or InstagramMetaClient(self.settings)
        self.sleep = sleep
        configured_id = self.settings.worker_id.strip()
        self.worker_id = configured_id or f"channel-{socket.gethostname()}-{os.getpid()}"
        self._stop_requested = False
        self._next_meta_schedule_at = 0.0

    def request_stop(self, *_args: object) -> None:
        self._stop_requested = True

    def _heartbeat(
        self, status: str, job_type: str | None = None, job_id: int | None = None
    ) -> None:
        with self.session_factory() as db:
            update_worker_heartbeat(
                db,
                worker_id=self.worker_id,
                status=status,
                current_job_type=job_type,
                current_job_id=job_id,
                version=f"{self.settings.app_version}:{self.settings.app_release_id}"[:80],
                hostname=socket.gethostname(),
            )
            db.commit()

    def _claim(self) -> tuple[list[int], list[int]]:
        with self.session_factory() as db:
            inbox_ids = claim_inbox_jobs(
                db,
                worker_id=self.worker_id,
                limit=self.settings.worker_batch_size,
                lock_timeout_seconds=self.settings.worker_lock_timeout_seconds,
            )
            outbox_ids = claim_outbox_jobs(
                db,
                worker_id=self.worker_id,
                limit=self.settings.worker_batch_size,
                lock_timeout_seconds=self.settings.worker_lock_timeout_seconds,
            )
            db.commit()
            return inbox_ids, outbox_ids

    def _schedule_meta_jobs(self) -> int:
        current_monotonic = time.monotonic()
        if current_monotonic < self._next_meta_schedule_at:
            return 0
        with self.session_factory() as db:
            count = schedule_due_meta_jobs(db, settings=self.settings)
            db.commit()
        self._next_meta_schedule_at = current_monotonic + 60.0
        return count

    def _claim_meta_jobs(self) -> list[int]:
        with self.session_factory() as db:
            ids = claim_meta_integration_jobs(
                db,
                worker_id=self.worker_id,
                limit=self.settings.meta_integration_health_batch_size,
                lock_ttl_seconds=self.settings.meta_integration_health_lock_ttl_seconds,
            )
            db.commit()
            return ids

    def _process_inbox(self, inbox_id: int) -> None:
        started = time.monotonic()
        try:
            with self.session_factory() as db:
                row = db.get(WebhookInboxEvent, inbox_id)
                token = request_id_context.set(row.request_id if row else None)
                try:
                    result = process_channel_inbox_event(db, inbox_id)
                    db.commit()
                finally:
                    request_id_context.reset(token)
            logger.info(
                "queue_job_completed worker_id=%s job_type=inbox inbox_id=%s result=%s duration_ms=%s",
                self.worker_id,
                inbox_id,
                result.action,
                int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:
            with self.session_factory() as db:
                row = db.get(WebhookInboxEvent, inbox_id)
                if row and row.status == "processing":
                    classified_error = exc if isinstance(exc, ChannelInboxProcessingError) else None
                    permanent = bool(classified_error and not classified_error.retryable)
                    locked = is_sqlite_locked_error(exc)
                    error_code = "webhook_processing_failed"
                    safe_message = "Queue operation failed"
                    if classified_error is not None:
                        error_code = classified_error.error_code
                        safe_message = classified_error.safe_message
                    classification = classify_queue_error(
                        error_code=error_code,
                        database_locked=locked,
                    )
                    if classified_error is None:
                        safe_message = classification.safe_message
                    retryable = locked or (
                        not permanent
                        and (classified_error is None or classified_error.retryable)
                        and row.attempt_count < row.max_attempts
                    )
                    fail_inbox_job(
                        row,
                        error_code=classification.code,
                        safe_message=safe_message,
                        retryable=retryable,
                    )
                    if row.status in {"failed", "dead_letter"}:
                        report_incident(
                            db,
                            category="webhook_dead_letter"
                            if row.status == "dead_letter"
                            else "webhook_processing_failed",
                            severity="high",
                            business_id=row.business_id,
                            integration_id=row.integration_id,
                            channel=row.channel,
                            provider=row.provider,
                            provider_error_code=classification.code,
                            operation=f"process_inbox_{row.id}",
                            safe_details={"inbox_id": row.id, "attempt": row.attempt_count},
                        )
                    db.commit()
            logger.warning(
                "queue_job_failed worker_id=%s job_type=inbox inbox_id=%s safe_error_code=%s",
                self.worker_id,
                inbox_id,
                type(exc).__name__,
            )

    def _prepare_delivery(self, outbox_id: int) -> PreparedDelivery | None:
        with self.session_factory() as db:
            row = db.get(ChannelOutboxMessage, outbox_id)
            if row is None or row.status != "processing":
                return None
            message = (
                db.get(ConversationMessage, row.conversation_message_id)
                if row.conversation_message_id
                else None
            )
            business = db.get(Business, row.business_id)
            if business is None or business.status != "active":
                fail_outbox_job(
                    row,
                    message,
                    classification=classify_queue_error(
                        error_code="business_not_operational"
                    ),
                )
                db.commit()
                return None
            action = message.opportunity_action if message is not None else None
            if action is not None and (
                action.status == "cancelled" or action.opportunity.status != "pending"
            ):
                assert message is not None
                row.status = "cancelled"
                row.failed_at = datetime.utcnow()
                row.locked_by = None
                row.lock_expires_at = None
                row.next_retry_at = None
                row.safe_error_message = "Opportunity is no longer relevant"
                message.delivery_status = "cancelled"
                action.status = "cancelled"
                action.cancelled_at = datetime.utcnow()
                action.failure_reason = "opportunity_no_longer_relevant"
                db.commit()
                return None
            integration = db.get(BusinessChannelIntegration, row.integration_id)
            error_code = None
            sender = self.provider_senders.get(row.provider)
            if sender is None or not delivery_supported(
                channel=row.channel,
                provider=row.provider,
            ):
                error_code = "unsupported_channel_provider"
            elif integration is None or integration.business_id != row.business_id:
                error_code = "integration_not_configured"
            elif integration.channel != row.channel or integration.provider != row.provider:
                error_code = "integration_not_configured"
            elif integration.integration_status not in {"connected", "degraded"}:
                error_code = f"integration_{integration.integration_status}"
            elif integration_health_blocks_delivery(integration):
                error_code = "integration_unavailable"
            elif integration_credentials_expired(integration):
                error_code = "integration_expired"
            elif not integration.encrypted_access_token or not integration.encryption_key_version:
                error_code = "integration_not_configured"
            if error_code:
                fail_outbox_job(
                    row, message, classification=classify_queue_error(error_code=error_code)
                )
                self._report_outbox_failure(db, row)
                db.commit()
                return None
            integration = cast(BusinessChannelIntegration, integration)
            ciphertext = integration.encrypted_access_token
            key_version = integration.encryption_key_version
            if ciphertext is None or key_version is None:
                raise RuntimeError("Integration credentials changed while preparing delivery")
            try:
                token = decrypt_secret(
                    ciphertext,
                    key_version,
                    settings=self.settings,
                )
            except IntegrationCryptoError:
                fail_outbox_job(
                    row,
                    message,
                    classification=classify_queue_error(error_code="integration_decryption_failed"),
                )
                self._report_outbox_failure(db, row)
                db.commit()
                return None
            try:
                payload = json.loads(row.payload_json)
                text = payload["text"]
                if not isinstance(text, str) or not text.strip():
                    raise ValueError
            except (TypeError, ValueError, KeyError):
                fail_outbox_job(
                    row, message, classification=classify_queue_error(error_code="invalid_payload")
                )
                self._report_outbox_failure(db, row)
                db.commit()
                return None
            prepared = PreparedDelivery(
                row.id,
                row.business_id,
                row.integration_id,
                row.recipient_external_id,
                text,
                token,
                integration.external_account_id,
                cast(ProviderSender, sender),
            )
            db.commit()
            return prepared

    def _report_outbox_failure(self, db: Session, row: ChannelOutboxMessage) -> None:
        category = (
            "outbox_dead_letter"
            if row.status == "dead_letter"
            else (
                "provider_rate_limited"
                if row.last_error_code == "provider_rate_limited"
                else (
                    "integration_unavailable" if row.status == "blocked" else "outbox_send_failed"
                )
            )
        )
        report_incident(
            db,
            category=category,
            severity="high" if row.status in {"blocked", "dead_letter"} else "medium",
            business_id=row.business_id,
            integration_id=row.integration_id,
            channel=row.channel,
            provider=row.provider,
            provider_error_code=row.last_error_code,
            operation=f"process_outbox_{row.id}",
            conversation_id=row.conversation_id,
            message_id=row.conversation_message_id,
            safe_details={"outbox_id": row.id, "attempt": row.attempt_count, "status": row.status},
        )
        message = (
            db.get(ConversationMessage, row.conversation_message_id)
            if row.conversation_message_id
            else None
        )
        if message is not None and message.opportunity_action is not None:
            record_audit(
                db,
                action="action_failed",
                business_id=row.business_id,
                resource_type="opportunity_action",
                resource_id=message.opportunity_action.id,
                metadata={
                    "channel": row.channel,
                    "outbox_status": row.status,
                    "reason": row.last_error_code,
                },
                commit=False,
            )

    def _process_outbox(self, outbox_id: int) -> None:
        prepared = self._prepare_delivery(outbox_id)
        if prepared is None or not self._authorize_delivery(outbox_id):
            return
        # The provider call intentionally runs with no Session/transaction open.
        result = prepared.sender(
            prepared.recipient_id,
            prepared.text,
            access_token=prepared.access_token,
            external_account_id=prepared.external_account_id,
            settings=self.settings,
            timeout_seconds=self.settings.worker_job_timeout_seconds,
        )
        with self.session_factory() as db:
            row = db.get(ChannelOutboxMessage, outbox_id)
            if row is None or row.status != "processing":
                return
            message = (
                db.get(ConversationMessage, row.conversation_message_id)
                if row.conversation_message_id
                else None
            )
            integration = db.get(BusinessChannelIntegration, row.integration_id)
            if result.ok:
                finish_outbox_job(row, message, provider_message_id=result.provider_message_id)
                if message is not None and message.opportunity_action is not None:
                    record_audit(
                        db,
                        action="action_sent",
                        business_id=row.business_id,
                        resource_type="opportunity_action",
                        resource_id=message.opportunity_action.id,
                        metadata={"channel": row.channel, "outbox_id": row.id},
                        commit=False,
                    )
                if integration:
                    integration.last_success_at = datetime.utcnow()
                    integration.last_error_code = None
                    integration.safe_error_message = None
                resolve_related_incidents(
                    db,
                    business_id=row.business_id,
                    integration_id=row.integration_id,
                    channel=row.channel,
                    provider=row.provider,
                    operation=f"process_outbox_{row.id}",
                )
            else:
                error_code = result.error_code or (
                    "connection_error" if result.http_status is None else "provider_rejected"
                )
                classification = classify_queue_error(
                    error_code=error_code,
                    http_status=result.http_status,
                    timed_out=result.timed_out,
                )
                if row.provider == "whatsapp" and error_code in {
                    "invalid_recipient",
                    "whatsapp_template_required",
                }:
                    classification = QueueErrorClassification(
                        error_code,
                        retryable=False,
                        safe_message="Queue operation failed permanently",
                    )
                fail_outbox_job(
                    row,
                    message,
                    classification=classification,
                    http_status=result.http_status,
                    error_subcode=result.error_subcode,
                    error_type=result.error_type,
                )
                if integration:
                    if result.error_code == "190":
                        integration.integration_status = (
                            "expired" if result.error_subcode == "463" else "revoked"
                        )
                        integration.health_status = (
                            "action_required" if result.error_subcode == "463" else "revoked"
                        )
                    elif result.error_code in {"token_expired", "token_revoked"}:
                        integration.integration_status = (
                            "expired" if result.error_code == "token_expired" else "revoked"
                        )
                        integration.health_status = (
                            "action_required" if result.error_code == "token_expired" else "revoked"
                        )
                    elif result.error_code in {
                        "account_suspended",
                        "insufficient_permissions",
                        "invalid_phone_number_id",
                        "number_not_registered",
                    }:
                        integration.integration_status = "error"
                        integration.health_status = (
                            "suspended"
                            if result.error_code == "account_suspended"
                            else "action_required"
                        )
                    integration.last_error_at = datetime.utcnow()
                    integration.last_error_code = result.error_code
                    integration.last_error_subcode = result.error_subcode
                    integration.last_error_type = result.error_type
                    integration.safe_error_message = classification.safe_message
                self._report_outbox_failure(db, row)
            db.commit()

    def _authorize_delivery(self, outbox_id: int) -> bool:
        """Recheck tenant state immediately before the external provider call."""

        with self.session_factory() as db:
            row = db.get(ChannelOutboxMessage, outbox_id)
            if row is None or row.status != "processing":
                return False
            business = db.get(Business, row.business_id)
            if business is not None and business.status == "active":
                return True
            message = (
                db.get(ConversationMessage, row.conversation_message_id)
                if row.conversation_message_id
                else None
            )
            fail_outbox_job(
                row,
                message,
                classification=classify_queue_error(error_code="business_not_operational"),
            )
            db.commit()
            return False

    def _prepare_meta_health_job(self, job_id: int) -> PreparedMetaHealthJob | None:
        with self.session_factory() as db:
            job = db.get(MetaIntegrationJob, job_id)
            if job is None or job.status != "processing" or job.integration_id is None:
                return None
            integration = db.get(BusinessChannelIntegration, job.integration_id)
            error_code = None
            checker: IntegrationHealthChecker | None = None
            if integration is None or integration.business_id != job.business_id:
                error_code = "integration_not_configured"
            elif integration.channel != integration.provider:
                error_code = "integration_provider_mismatch"
            else:
                try:
                    checker = health_checker_for_provider(integration.provider)
                except UnsupportedIntegrationHealthProvider:
                    error_code = "unsupported_integration_provider"
            if integration is not None and error_code is None:
                conflict_filters = [
                    BusinessChannelIntegration.id != integration.id,
                    BusinessChannelIntegration.business_id != job.business_id,
                    BusinessChannelIntegration.provider == integration.provider,
                ]
                if integration.provider == "whatsapp" and integration.provider_account_id:
                    conflict_filters.append(
                        or_(
                            BusinessChannelIntegration.external_account_id
                            == integration.external_account_id,
                            BusinessChannelIntegration.provider_account_id
                            == integration.provider_account_id,
                        )
                    )
                else:
                    conflict_filters.append(
                        BusinessChannelIntegration.external_account_id
                        == integration.external_account_id
                    )
                conflict = db.query(BusinessChannelIntegration.id).filter(*conflict_filters)
                if conflict.first() is not None:
                    error_code = "integration_tenant_conflict"
            if (
                integration is not None
                and error_code is None
                and (
                    not integration.encrypted_access_token or not integration.encryption_key_version
                )
            ):
                error_code = "integration_credentials_missing"
            if error_code is not None:
                if integration is not None:
                    checked_at = datetime.utcnow()
                    integration.health_status = "error"
                    integration.last_health_check_at = checked_at
                    integration.next_health_check_at = None
                    integration.consecutive_health_failures += 1
                    integration.health_error_code = error_code
                    integration.health_safe_error_message = (
                        "Integration health check is unavailable"
                    )
                    integration.health_metadata_json = json.dumps(
                        {
                            "asset_status": "invalid",
                            "blocking": True,
                            "reconnection_required": True,
                            "subscription_status": "unknown",
                            "token_expiry_status": "unknown",
                        },
                        sort_keys=True,
                    )
                    integration.last_error_at = checked_at
                fail_meta_integration_job(
                    db,
                    job,
                    error_code=error_code,
                    safe_message="Integration health check is unavailable",
                    retryable=False,
                    duration_ms=0,
                )
                db.commit()
                return None
            if integration is None or checker is None:
                fail_meta_integration_job(
                    db,
                    job,
                    error_code="health_preparation_failed",
                    safe_message="Integration health check could not be prepared",
                    retryable=False,
                    duration_ms=0,
                )
                db.commit()
                return None
            try:
                token = decrypt_secret(
                    integration.encrypted_access_token or "",
                    integration.encryption_key_version or "",
                    settings=self.settings,
                )
            except IntegrationCryptoError:
                integration.health_status = "error"
                integration.health_error_code = "integration_decryption_failed"
                integration.health_safe_error_message = "Integration credentials could not be read"
                fail_meta_integration_job(
                    db,
                    job,
                    error_code="integration_decryption_failed",
                    safe_message="Integration credentials could not be read",
                    retryable=False,
                    duration_ms=0,
                )
                db.commit()
                return None
            db.expunge(integration)
            db.commit()
            return PreparedMetaHealthJob(
                job_id=job.id,
                business_id=job.business_id,
                integration_id=integration.id,
                job_type=job.job_type,
                integration=integration,
                access_token=token,
                checker=checker,
            )

    @staticmethod
    def _sync_error(error: Exception) -> tuple[str, str, bool]:
        if isinstance(error, MetaHTTPError):
            if error.authentication:
                return "instagram_authentication_failed", "Instagram must be reconnected", False
            if error.permission:
                return "instagram_permission_denied", "Instagram permissions are insufficient", False
            return (
                (error.error_code or "instagram_provider_error")[:120],
                "Instagram could not be updated. Existing media was preserved",
                error.retryable,
            )
        if isinstance(error, requests.RequestException):
            return (
                "instagram_provider_unreachable",
                "Instagram could not be updated. Existing media was preserved",
                True,
            )
        return (
            "instagram_media_sync_failed",
            "Instagram could not be updated. Existing media was preserved",
            True,
        )

    def _fail_instagram_media_sync(
        self, job_id: int, *, error: Exception, started: float
    ) -> None:
        error_code, safe_message, retryable = self._sync_error(error)
        with self.session_factory() as db:
            job = db.get(MetaIntegrationJob, job_id)
            state = (
                db.query(InstagramMediaSyncState)
                .filter(InstagramMediaSyncState.integration_id == job.integration_id)
                .first()
                if job and job.integration_id
                else None
            )
            if job is None or job.status != "processing":
                return
            if state is not None:
                mark_sync_failed(
                    db,
                    state=state,
                    job_id=job.id,
                    error_code=error_code,
                    safe_message=safe_message,
                )
            fail_meta_integration_job(
                db,
                job,
                error_code=error_code,
                safe_message=safe_message,
                retryable=retryable,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            db.commit()

    def _process_instagram_media_sync(self, job_id: int, *, started: float) -> None:
        try:
            with self.session_factory() as db:
                job = db.get(MetaIntegrationJob, job_id)
                if job is None or job.status != "processing" or job.integration_id is None:
                    return
                integration = (
                    db.query(BusinessChannelIntegration)
                    .filter(
                        BusinessChannelIntegration.id == job.integration_id,
                        BusinessChannelIntegration.business_id == job.business_id,
                        BusinessChannelIntegration.channel == "instagram",
                        BusinessChannelIntegration.provider == "instagram",
                    )
                    .first()
                )
                state = (
                    db.query(InstagramMediaSyncState)
                    .filter(
                        InstagramMediaSyncState.integration_id == job.integration_id,
                        InstagramMediaSyncState.business_id == job.business_id,
                    )
                    .first()
                )
                if (
                    integration is None
                    or state is None
                    or not state.run_id
                    or not integration.encrypted_access_token
                    or not integration.encryption_key_version
                ):
                    raise ValueError("Instagram media sync is not prepared")
                token = decrypt_secret(
                    integration.encrypted_access_token,
                    integration.encryption_key_version,
                    settings=self.settings,
                )
                business_id = job.business_id
                integration_id = integration.id
                account_id = integration.external_account_id
                run_id = state.run_id
                after_cursor = state.after_cursor
                mark_sync_started(db, state=state, job=job)
                db.commit()

            page = self.instagram_media_client.list_account_media(
                account_id=account_id,
                access_token=token,
                after_cursor=after_cursor,
                limit=self.settings.instagram_media_sync_page_size,
            )
            page_items: list[
                tuple[InstagramRemoteMediaItem, tuple[InstagramRemoteMediaItem, ...]]
            ] = []
            for item in page.items:
                children: list[InstagramRemoteMediaItem] = []
                if item.media_type == "CAROUSEL_ALBUM":
                    child_cursor = None
                    for _ in range(5):
                        child_page = self.instagram_media_client.list_media_children(
                            media_id=item.provider_media_id,
                            access_token=token,
                            after_cursor=child_cursor,
                            limit=25,
                        )
                        children.extend(child_page.items)
                        child_cursor = child_page.after_cursor
                        if not child_cursor:
                            break
                    if child_cursor:
                        raise ValueError("Instagram carousel pagination exceeded safe bound")
                page_items.append((item, tuple(children)))

            with self.session_factory() as db:
                state = (
                    db.query(InstagramMediaSyncState)
                    .filter(
                        InstagramMediaSyncState.integration_id == integration_id,
                        InstagramMediaSyncState.run_id == run_id,
                    )
                    .first()
                )
                if state is None:
                    return
                result = persist_media_page(
                    db,
                    business_id=business_id,
                    integration_id=integration_id,
                    run_id=run_id,
                    items=tuple(page_items),
                )
                candidates = (
                    unavailable_probe_candidates(
                        db,
                        integration_id=integration_id,
                        run_id=run_id,
                        limit=self.settings.instagram_media_unavailable_probe_limit,
                    )
                    if page.after_cursor is None
                    else []
                )
                db.commit()

            probe_results: list[tuple[int, InstagramRemoteMediaItem | None, str | None]] = []
            for media_id, provider_media_id in candidates:
                try:
                    refreshed = self.instagram_media_client.get_media(
                        media_id=provider_media_id,
                        access_token=token,
                    )
                    probe_results.append((media_id, refreshed, None))
                except MetaHTTPError as error:
                    if not error.unavailable:
                        raise
                    probe_results.append((media_id, None, error.error_code))

            with self.session_factory() as db:
                job = db.get(MetaIntegrationJob, job_id)
                state = (
                    db.query(InstagramMediaSyncState)
                    .filter(
                        InstagramMediaSyncState.integration_id == integration_id,
                        InstagramMediaSyncState.run_id == run_id,
                    )
                    .first()
                )
                if job is None or job.status != "processing" or state is None:
                    return
                unavailable_count = 0
                for media_id, probe_item, error_code in probe_results:
                    if probe_item is None:
                        unavailable_count += int(
                            mark_media_unavailable(
                                db,
                                business_id=business_id,
                                integration_id=integration_id,
                                media_id=media_id,
                                error_code=error_code,
                            )
                        )
                    else:
                        mark_probe_available(
                            db,
                            business_id=business_id,
                            integration_id=integration_id,
                            media_id=media_id,
                            item=probe_item,
                        )
                advance_or_finish_sync(
                    db,
                    state=state,
                    job_id=job.id,
                    after_cursor=page.after_cursor,
                    result=result,
                    unavailable_count=unavailable_count,
                )
                finish_meta_integration_job(
                    db,
                    job,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                if page.after_cursor is not None:
                    enqueue_instagram_media_sync(
                        db,
                        business_id=business_id,
                        origin="system",
                        settings=self.settings,
                    )
                db.commit()
        except (MetaHTTPError, requests.RequestException, IntegrationCryptoError, ValueError) as error:
            self._fail_instagram_media_sync(job_id, error=error, started=started)
        except Exception as error:
            logger.exception("instagram_media_sync_unexpected_failure job_id=%s", job_id)
            self._fail_instagram_media_sync(job_id, error=error, started=started)

    def _process_meta_job(self, job_id: int) -> None:
        started = time.monotonic()
        with self.session_factory() as type_db:
            current_job = type_db.get(MetaIntegrationJob, job_id)
            if current_job is None or current_job.status != "processing":
                return
            business = type_db.get(Business, current_job.business_id)
            if business is None or business.status != "active":
                fail_meta_integration_job(
                    type_db,
                    current_job,
                    error_code="business_not_operational",
                    safe_message="Integration work is disabled while the business is not active",
                    retryable=False,
                    duration_ms=0,
                )
                type_db.commit()
                return
            job_type = current_job.job_type
        if job_type == "instagram_media_sync":
            self._process_instagram_media_sync(job_id, started=started)
            return
        with self.session_factory() as db:
            job = db.get(MetaIntegrationJob, job_id)
            if job is None or job.status != "processing":
                return
            if job.job_type == "attempt_cleanup":
                try:
                    cleanup_meta_integration_attempts(
                        db,
                        business_id=job.business_id,
                        settings=self.settings,
                    )
                    finish_meta_integration_job(
                        db, job, duration_ms=int((time.monotonic() - started) * 1000)
                    )
                    db.commit()
                except Exception:
                    db.rollback()
                    with self.session_factory() as failure_db:
                        failed_job = failure_db.get(MetaIntegrationJob, job_id)
                        if failed_job and failed_job.status == "processing":
                            fail_meta_integration_job(
                                failure_db,
                                failed_job,
                                error_code="attempt_cleanup_failed",
                                safe_message="Temporary integration attempts could not be cleaned",
                                retryable=True,
                                duration_ms=int((time.monotonic() - started) * 1000),
                            )
                            failure_db.commit()
                return

        prepared = self._prepare_meta_health_job(job_id)
        if prepared is None:
            return
        try:
            result = prepared.checker(
                prepared.integration,
                access_token=prepared.access_token,
                settings=self.settings,
                repair_subscription=prepared.job_type == "retry_subscription",
            )
        except Exception:
            with self.session_factory() as db:
                job = db.get(MetaIntegrationJob, job_id)
                if job and job.status == "processing":
                    fail_meta_integration_job(
                        db,
                        job,
                        error_code="health_checker_failed",
                        safe_message="Integration health check failed safely",
                        retryable=True,
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )
                    db.commit()
            logger.warning(
                "meta_integration_job_failed worker_id=%s job_id=%s",
                self.worker_id,
                job_id,
            )
            return
        with self.session_factory() as db:
            job = db.get(MetaIntegrationJob, job_id)
            integration = db.get(BusinessChannelIntegration, prepared.integration_id)
            if (
                job is None
                or job.status != "processing"
                or integration is None
                or integration.business_id != prepared.business_id
            ):
                return
            apply_integration_health_result(
                db,
                job=job,
                integration=integration,
                result=result,
                settings=self.settings,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            transient_failure = result.retryable and (
                result.subscription_status != "missing" or prepared.job_type == "retry_subscription"
            )
            if transient_failure:
                fail_meta_integration_job(
                    db,
                    job,
                    error_code=result.safe_error_code or "provider_temporarily_unavailable",
                    safe_message=result.safe_error_message or "Provider is temporarily unavailable",
                    retryable=True,
                    duration_ms=duration_ms,
                )
            else:
                finish_meta_integration_job(db, job, duration_ms=duration_ms)
                if result.subscription_status == "missing" and job.job_type == "health_check":
                    enqueue_meta_integration_job(
                        db,
                        business_id=integration.business_id,
                        integration_id=integration.id,
                        job_type="retry_subscription",
                        origin="system",
                        max_attempts=self.settings.meta_integration_failure_threshold,
                    )
                if job.job_type == "retry_subscription" and result.healthy:
                    from app.core.audit import record_audit

                    record_audit(
                        db,
                        action="subscription_retry_succeeded",
                        business_id=integration.business_id,
                        resource_type="business_channel_integration",
                        resource_id=integration.id,
                        metadata={"job_id": job.id, "channel": integration.channel},
                        commit=False,
                    )
            db.commit()

    def run_once(self) -> int:
        self._heartbeat("idle")
        if getattr(self.settings, "maintenance_worker_mode", "continue") == "pause":
            with self.session_factory() as db:
                if maintenance_enabled(db):
                    return 0
        inbox_ids, outbox_ids = self._claim()
        for inbox_id in inbox_ids:
            if self._stop_requested:
                break
            self._heartbeat("processing", "inbox", inbox_id)
            self._process_inbox(inbox_id)
        for outbox_id in outbox_ids:
            if self._stop_requested:
                break
            self._heartbeat("processing", "outbox", outbox_id)
            self._process_outbox(outbox_id)
        self._schedule_meta_jobs()
        meta_ids = self._claim_meta_jobs()
        for job_id in meta_ids:
            if self._stop_requested:
                break
            self._heartbeat("processing", "meta_integration", job_id)
            self._process_meta_job(job_id)
        self._heartbeat("idle")
        return len(inbox_ids) + len(outbox_ids) + len(meta_ids)

    def run_forever(self) -> None:
        self._heartbeat("starting")
        while not self._stop_requested:
            try:
                jobs = self.run_once()
            except Exception as exc:
                if isinstance(exc, (DBAPIError, SQLAlchemyTimeoutError)):
                    classification = classify_database_error(exc)
                    try:
                        with self.session_factory() as db:
                            report_database_incident(
                                db,
                                exc,
                                operation="channel_worker_cycle",
                            )
                            db.commit()
                    except Exception as incident_error:
                        logger.error(
                            "channel_worker_database_failure worker_id=%s "
                            "incident_persistence=failed error_type=%s",
                            self.worker_id,
                            type(incident_error).__name__,
                        )
                    logger.error(
                        "channel_worker_database_failure worker_id=%s category=%s retryable=%s",
                        self.worker_id,
                        classification.code,
                        classification.retryable,
                    )
                else:
                    logger.exception("channel_worker_cycle_failed worker_id=%s", self.worker_id)
                try:
                    self._heartbeat("error")
                except Exception as heartbeat_error:
                    logger.error(
                        "channel_worker_error_heartbeat_failed worker_id=%s error_type=%s",
                        self.worker_id,
                        type(heartbeat_error).__name__,
                    )
                jobs = 0
            if not jobs and not self._stop_requested:
                self.sleep(self.settings.worker_poll_interval_seconds)
        self._heartbeat("stopping")
        self._heartbeat("stopped")


def main() -> int:
    settings = get_settings()
    if not settings.worker_enabled:
        logger.info("channel_worker_disabled")
        return 0
    worker = ChannelWorker(settings=settings)
    signal.signal(signal.SIGTERM, worker.request_stop)
    signal.signal(signal.SIGINT, worker.request_stop)
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
