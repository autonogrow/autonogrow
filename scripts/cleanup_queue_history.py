"""Dry-run-first retention cleanup for completed persistent queue records."""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.audit import record_audit  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    ChannelOutboxMessage,
    SystemIncident,
    WebhookInboxEvent,
    WorkerHeartbeat,
)


def cleanup(
    *,
    apply: bool = False,
    session_factory=SessionLocal,
    settings=None,
    now: datetime | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    now = now or datetime.utcnow()
    with session_factory() as db:
        inbox = (
            db.query(WebhookInboxEvent)
            .filter(
                WebhookInboxEvent.status.in_({"processed", "ignored"}),
                WebhookInboxEvent.processed_at
                < now - timedelta(days=settings.webhook_inbox_retention_days),
            )
            .all()
        )
        outbox = (
            db.query(ChannelOutboxMessage)
            .filter(
                ChannelOutboxMessage.status == "sent",
                ChannelOutboxMessage.sent_at < now - timedelta(days=settings.outbox_retention_days),
            )
            .all()
        )
        heartbeats = (
            db.query(WorkerHeartbeat)
            .filter(
                WorkerHeartbeat.last_seen_at
                < now - timedelta(days=settings.worker_heartbeat_retention_days)
            )
            .all()
        )
        open_operations = {
            value
            for (value,) in db.query(SystemIncident.operation)
            .filter(SystemIncident.status.in_({"open", "acknowledged"}))
            .all()
        }
        inbox = [row for row in inbox if f"process_inbox_{row.id}" not in open_operations]
        outbox = [row for row in outbox if f"process_outbox_{row.id}" not in open_operations]
        result = {
            "inbox": len(inbox),
            "outbox": len(outbox),
            "heartbeats": len(heartbeats),
            "estimated_payload_bytes": sum(row.payload_size_bytes for row in inbox)
            + sum(len(row.payload_json.encode("utf-8")) for row in outbox),
        }
        if apply:
            for row in (*inbox, *outbox, *heartbeats):
                db.delete(row)
            record_audit(
                db,
                action="queue_history_cleanup",
                resource_type="queue_retention",
                metadata=result,
                commit=False,
            )
            db.commit()
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Delete eligible completed records")
    args = parser.parse_args()
    result = cleanup(apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
