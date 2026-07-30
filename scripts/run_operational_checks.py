"""Run one bounded operational health and alert evaluation iteration."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.database import SessionLocal  # noqa: E402
from app.services.operational_alert_service import (  # noqa: E402
    evaluate_operational_alerts,
    persist_operational_alerts,
)
from app.services.operational_health_service import (  # noqa: E402
    owner_system_health,
    readiness_checks,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--dry-run", action="store_true", default=False)
    value.add_argument("--no-notify", action="store_true")
    value.add_argument("--json", action="store_true")
    value.add_argument("--component")
    return value


def build_snapshot(health: dict, ready: bool) -> dict:
    queues = health["queues"]
    backlog = sum(queues["inbox"].get(status, 0) for status in ("pending", "retry", "processing"))
    backlog += sum(
        queues["outbox"].get(status, 0) for status in ("pending", "retry", "processing", "blocked")
    )
    dead_letters = queues["inbox"].get("dead_letter", 0) + queues["outbox"].get("dead_letter", 0)
    oldest_seconds = 0.0
    if queues["oldest_pending_at"]:
        oldest = datetime.fromisoformat(queues["oldest_pending_at"])
        oldest_seconds = max(0.0, (datetime.utcnow() - oldest).total_seconds())
    return {
        "ready": ready,
        "workers": health["workers"],
        "queues": {
            "backlog": backlog,
            "dead_letters": dead_letters,
            "oldest_seconds": oldest_seconds,
        },
        "storage": health["storage"],
        "backups": health["backups"],
        "database": health["database"],
        "integrations": health["integrations"],
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        ready, _ = readiness_checks()
        with SessionLocal() as db:
            snapshot = build_snapshot(owner_system_health(db), ready)
            signals = evaluate_operational_alerts(snapshot)
            if args.component:
                signals = [signal for signal in signals if signal.component == args.component]
            changes = {"opened": 0, "updated": 0, "resolved": 0, "notified": 0}
            if not args.dry_run:
                changes = persist_operational_alerts(db, signals, notify=not args.no_notify)
                db.commit()
        result = {
            "status": "critical"
            if any(item.severity == "critical" for item in signals)
            else "warning"
            if signals
            else "ok",
            "alerts": [
                {
                    "component": item.component,
                    "condition": item.condition,
                    "severity": item.severity,
                }
                for item in signals
            ],
            "changes": changes,
            "dry_run": args.dry_run,
        }
        print(
            json.dumps(result, sort_keys=True)
            if args.json
            else f"Operational checks: {result['status']} ({len(signals)} alerts)"
        )
        return 2 if result["status"] == "critical" else 1 if result["status"] == "warning" else 0
    except Exception as exc:
        print(
            json.dumps({"status": "technical_error", "error": type(exc).__name__})
            if args.json
            else f"Operational checks failed: {type(exc).__name__}"
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
