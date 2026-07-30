"""Coordinate PostgreSQL and uploads artifacts under one backup-set identifier."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.backup_common import backup_set_id  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output-dir")
    args = parser.parse_args(argv)
    set_id = backup_set_id()
    common = ["--backup-set-id", set_id]
    if args.output_dir:
        common += ["--output-dir", args.output_dir]
    if args.apply:
        common.append("--apply")
    for script in ("backup_postgresql.py", "backup_uploads.py"):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), *common], check=False
        )
        if completed.returncode:
            return completed.returncode
    print(f"Backup set complete: {set_id}" if args.apply else f"DRY-RUN backup set: {set_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
