"""Plan a compatibility-aware code rollback. Dry-run by default; never downgrades the database."""

from __future__ import annotations

import argparse
import json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-release", required=True)
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--compatibility-confirmed", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    steps = [
        "check_target",
        "check_schema_compatibility",
        "enable_maintenance",
        "stop_worker",
        "switch_release",
        "start_backend",
        "readiness",
        "start_worker",
        "smoke_test",
        "record_rollback",
    ]
    payload = {
        "target_release": args.target_release,
        "environment": args.environment,
        "apply": args.apply,
        "steps": steps,
        "database_downgrade": False,
        "restore_automatic": False,
    }
    if args.apply and not args.compatibility_confirmed:
        parser.error("--apply requires --compatibility-confirmed")
    print(
        json.dumps(payload, sort_keys=True)
        if args.json
        else f"{'Rollback plan' if not args.apply else 'Validated rollback handoff'}: {len(steps)} steps"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
