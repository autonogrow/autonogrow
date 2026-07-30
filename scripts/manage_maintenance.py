"""Inspect or change persistent maintenance mode; changes require --apply."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.audit import record_audit  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.services.maintenance_service import maintenance_state, set_maintenance  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("enable", "disable", "status"))
    parser.add_argument("--reason", default="Command line operational action")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        row = maintenance_state(db)
        if args.action == "status":
            payload = {
                "enabled": bool(row and row.enabled),
                "reason": row.safe_reason if row else None,
            }
        elif not args.apply:
            payload = {
                "dry_run": True,
                "enabled": args.action == "enable",
                "reason": args.reason[:500],
            }
        else:
            row = set_maintenance(db, enabled=args.action == "enable", safe_reason=args.reason)
            record_audit(
                db,
                action=f"maintenance_{args.action}d",
                resource_type="operational_state",
                resource_id=row.id,
                metadata={"source": "cli", "enabled": row.enabled, "reason": row.safe_reason},
                commit=False,
            )
            db.commit()
            payload = {"enabled": row.enabled, "reason": row.safe_reason}
    print(
        json.dumps(payload, sort_keys=True)
        if args.json
        else f"Maintenance enabled: {payload.get('enabled')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
