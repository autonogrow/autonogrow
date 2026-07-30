import json
import logging
import os
import signal
import socket
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, cast

from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal, is_sqlite_locked_error
from app.core.observability import request_id_context
from app.models import (
    BusinessChannelIntegration,
    ChannelOutboxMessage,
    ConversationMessage,
    WebhookInboxEvent,
)
from app.services.database_error_service import classify_database_error, report_database_incident
from app.services.inbox_queue_service import claim_inbox_jobs, fail_inbox_job
from app.services.incident_service import report_incident, resolve_related_incidents
from app.services.instagram_inbox_processor import (
    InvalidInboxPayload,
    process_instagram_inbox_event,
)
from app.services.instagram_integration_service import integration_expiration_state
from app.services.instagram_provider import ProviderSendResult, send_instagram_text_message
from app.services.integration_crypto_service import IntegrationCryptoError, decrypt_secret
from app.services.maintenance_service import maintenance_enabled
from app.services.outbox_queue_service import claim_outbox_jobs, fail_outbox_job, finish_outbox_job
from app.services.queue_error_service import classify_queue_error
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


ProviderSender = Callable[..., ProviderSendResult]


class ChannelWorker:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_factory: sessionmaker[Session] = SessionLocal,
        provider_sender: ProviderSender = send_instagram_text_message,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory
        self.provider_sender = provider_sender
        self.sleep = sleep
        configured_id = self.settings.worker_id.strip()
        self.worker_id = configured_id or f"channel-{socket.gethostname()}-{os.getpid()}"
        self._stop_requested = False

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

    def _process_inbox(self, inbox_id: int) -> None:
        started = time.monotonic()
        try:
            with self.session_factory() as db:
                row = db.get(WebhookInboxEvent, inbox_id)
                token = request_id_context.set(row.request_id if row else None)
                try:
                    result = process_instagram_inbox_event(db, inbox_id)
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
                    permanent = isinstance(exc, InvalidInboxPayload)
                    locked = is_sqlite_locked_error(exc)
                    classification = classify_queue_error(
                        error_code="invalid_payload" if permanent else "webhook_processing_failed",
                        database_locked=locked,
                    )
                    retryable = locked or (not permanent and row.attempt_count < row.max_attempts)
                    fail_inbox_job(
                        row,
                        error_code=classification.code,
                        safe_message=classification.safe_message,
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
            integration = db.get(BusinessChannelIntegration, row.integration_id)
            error_code = None
            if integration is None or integration.business_id != row.business_id:
                error_code = "integration_not_configured"
            elif integration.integration_status not in {"connected", "degraded"}:
                error_code = f"integration_{integration.integration_status}"
            elif integration_expiration_state(integration)[0]:
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

    def _process_outbox(self, outbox_id: int) -> None:
        prepared = self._prepare_delivery(outbox_id)
        if prepared is None:
            return
        # The provider call intentionally runs with no Session/transaction open.
        result = self.provider_sender(
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
                if integration:
                    integration.integration_status = "connected"
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
                classification = classify_queue_error(
                    error_code=result.error_code
                    or ("connection_error" if result.http_status is None else "provider_rejected"),
                    http_status=result.http_status,
                    timed_out=result.timed_out,
                )
                fail_outbox_job(
                    row,
                    message,
                    classification=classification,
                    http_status=result.http_status,
                    error_subcode=result.error_subcode,
                    error_type=result.error_type,
                )
                if integration and result.error_code == "190":
                    integration.integration_status = (
                        "expired" if result.error_subcode == "463" else "revoked"
                    )
                self._report_outbox_failure(db, row)
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
        self._heartbeat("idle")
        return len(inbox_ids) + len(outbox_ids)

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
