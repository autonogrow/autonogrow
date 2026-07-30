"""Select the newest PostgreSQL manifest and hand it to the isolated restore tester."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.backup_common import load_manifest  # noqa: E402
from scripts.test_postgresql_restore import main as restore_main  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    directory = Path(args.backup_dir or get_settings().backup_dir).resolve()
    candidates: list[tuple[str, Path]] = []
    for path in directory.glob("*.manifest.json"):
        try:
            manifest = load_manifest(path)
            if manifest.get("backup_type") == "postgresql" and manifest.get("status") == "valid":
                candidates.append((str(manifest["created_at"]), path))
        except Exception:
            continue
    if not candidates:
        print("No valid PostgreSQL backup manifest found", file=sys.stderr)
        return 1
    manifest_path = max(candidates)[1]
    restore_args = [str(manifest_path)]
    if args.apply:
        restore_args.append("--apply")
    if args.json:
        restore_args.append("--json")
    return restore_main(restore_args)


if __name__ == "__main__":
    raise SystemExit(main())
