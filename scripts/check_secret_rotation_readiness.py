"""Check secret rotation prerequisites without printing secret values."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings()
    checks = {
        "session_secret_configured": len(settings.session_secret) >= 32,
        "integration_keyring_configured": bool(settings.integration_encryption_keys_json),
        "active_key_version_configured": bool(settings.integration_encryption_active_key_version),
        "smtp_credentials_consistent": bool(settings.smtp_username) == bool(settings.smtp_password),
    }
    ready = all(checks.values())
    payload = {
        "ready": ready,
        "checks": checks,
        "secrets_printed": False,
        "session_rotation_invalidates_sessions": True,
        "recipher_required_before_key_removal": True,
    }
    print(
        json.dumps(payload, sort_keys=True)
        if args.json
        else f"Secret rotation readiness: {'ready' if ready else 'not_ready'}"
    )
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
