"""Plan or apply bounded retention maintenance. Dry-run by default."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Business,
    ChannelOutboxMessage,
    WebhookInboxEvent,
    WorkerHeartbeat,
)
from app.services.business_growth_signal_service import (  # noqa: E402
    BusinessGrowthSignalService,
)
from app.services.growth_opportunity_service import GrowthOpportunityService  # noqa: E402

TASKS = ("queue-history", "heartbeats", "growth-opportunities", "growth-signals")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--task", choices=TASKS)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings()
    selected = (args.task,) if args.task else TASKS
    now = datetime.utcnow()
    counts: dict[str, int | dict[str, int]] = {}
    with SessionLocal() as db:
        if "queue-history" in selected:
            inbox_cutoff = now - timedelta(days=settings.webhook_inbox_retention_days)
            outbox_cutoff = now - timedelta(days=settings.outbox_retention_days)
            inbox = delete(WebhookInboxEvent).where(
                WebhookInboxEvent.status.in_(("processed", "ignored", "cancelled")),
                WebhookInboxEvent.updated_at < inbox_cutoff,
            )
            outbox = delete(ChannelOutboxMessage).where(
                ChannelOutboxMessage.status.in_(("sent", "cancelled")),
                ChannelOutboxMessage.updated_at < outbox_cutoff,
            )
            counts["queue_history"] = (
                (db.execute(inbox).rowcount or 0) + (db.execute(outbox).rowcount or 0)
                if args.apply
                else 0
            )
        if "heartbeats" in selected:
            statement = delete(WorkerHeartbeat).where(
                WorkerHeartbeat.status.in_(("stopped", "error")),
                WorkerHeartbeat.updated_at
                < now - timedelta(days=settings.worker_heartbeat_retention_days),
            )
            counts["heartbeats"] = db.execute(statement).rowcount or 0 if args.apply else 0
        if "growth-opportunities" in selected:
            totals = {"created": 0, "updated": 0, "resolved": 0, "expired": 0}
            business_ids = [
                row[0]
                for row in db.query(Business.id)
                .filter(Business.status.in_(("ready", "active")))
                .all()
            ]
            for business_id in business_ids:
                result = GrowthOpportunityService(db).evaluate_business(business_id)
                for key in totals:
                    totals[key] += getattr(result, key)
            counts["growth_opportunities"] = totals
        if "growth-signals" in selected:
            totals = {
                "created": 0,
                "updated": 0,
                "resolved": 0,
                "expired": 0,
                "suppressed": 0,
            }
            business_ids = [
                row[0]
                for row in db.query(Business.id)
                .filter(Business.status.in_(("ready", "active")))
                .all()
            ]
            for business_id in business_ids:
                result = BusinessGrowthSignalService(db).evaluate_business(business_id)
                for key in totals:
                    totals[key] += getattr(result, key)
            counts["growth_signals"] = totals
        if args.apply:
            db.commit()
        else:
            db.rollback()
    payload = {"dry_run": not args.apply, "tasks": selected, "deleted": counts}
    print(
        json.dumps(payload, sort_keys=True)
        if args.json
        else f"Maintenance {'applied' if args.apply else 'dry-run'}: {', '.join(selected)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
