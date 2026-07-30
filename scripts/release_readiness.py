"""Produce a read-only GO/NO-GO release decision without exposing configuration values."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_database_url, get_settings  # noqa: E402
from app.core.migration_state import inspect_database_migration_state  # noqa: E402


def evaluate() -> dict:
    settings = get_settings()
    checks: list[dict[str, str]] = []

    def add(name: str, status: str) -> None:
        checks.append({"check": name, "status": status})

    git = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    add("git_clean", "pass" if git.returncode == 0 and not git.stdout.strip() else "fail")
    add("release_metadata", "pass" if settings.app_release_id not in {"", "local"} else "warning")
    add(
        "keyring",
        "pass"
        if settings.integration_encryption_keys_json or not settings.instagram_provider_enabled
        else "fail",
    )
    try:
        engine = create_engine(get_database_url())
        state = inspect_database_migration_state(engine)
        add("database_at_head", "pass" if state.is_at_head else "fail")
        engine.dispose()
    except Exception:
        add("database_at_head", "fail")
    backup_dir = Path(settings.backup_dir) if settings.backup_dir else None
    add(
        "backup_available",
        "pass" if backup_dir and any(backup_dir.glob("*.manifest.json")) else "warning",
    )
    add("manual_validation", "warning")
    if any(item["status"] == "fail" for item in checks):
        decision = "NO-GO"
    elif any(item["status"] == "warning" for item in checks):
        decision = "GO-WITH-WARNINGS"
    else:
        decision = "GO"
    return {"decision": decision, "checks": checks, "read_only": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = evaluate()
    print(
        json.dumps(result, sort_keys=True)
        if args.json
        else f"Release decision: {result['decision']}"
    )
    return (
        2 if result["decision"] == "NO-GO" else 1 if result["decision"] == "GO-WITH-WARNINGS" else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
