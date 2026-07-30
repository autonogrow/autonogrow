"""Build a conservative deployment plan. Execution requires --apply and an identified release."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STEPS = (
    "validate_release",
    "predeploy_checks",
    "go_no_go",
    "verify_previous_release",
    "backup_database",
    "backup_uploads",
    "verify_backups",
    "enable_maintenance",
    "stop_worker",
    "prepare_release_directory",
    "install_locked_dependencies",
    "compile_assets",
    "alembic_upgrade",
    "switch_current_symlink",
    "start_backend",
    "wait_readiness",
    "start_worker",
    "verify_worker_heartbeat",
    "smoke_test",
    "disable_maintenance",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True)
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--skip-backup", action="store_true")
    parser.add_argument("--confirm-skip-backup")
    parser.add_argument("--keep-maintenance", action="store_true")
    parser.add_argument("--rollback-on-failure", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.skip_backup and args.confirm_skip_backup != "I_ACCEPT_NO_FRESH_BACKUP":
        parser.error("--skip-backup requires --confirm-skip-backup I_ACCEPT_NO_FRESH_BACKUP")
    plan = [
        step
        for step in STEPS
        if not (
            args.skip_backup and step in {"backup_database", "backup_uploads", "verify_backups"}
        )
    ]
    payload = {
        "release": args.release,
        "environment": args.environment,
        "apply": args.apply,
        "steps": plan,
        "implicit_git_pull": False,
    }
    if not args.apply:
        print(
            json.dumps(payload, sort_keys=True)
            if args.json
            else f"DRY-RUN deployment plan: {len(plan)} steps"
        )
        return 0
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "predeploy_check.py")], check=False
    )
    if completed.returncode:
        print("Deployment stopped: predeploy checks failed", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {**payload, "status": "predeploy_validated", "execution": "manual_steps_required"},
            sort_keys=True,
        )
        if args.json
        else "Predeploy validated; service-changing steps require the documented operator procedure"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
