"""Verify the newest manifest for each backup type in the configured directory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.backup_common import load_manifest  # noqa: E402
from scripts.verify_backup import verify  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    directory = Path(args.backup_dir or get_settings().backup_dir).resolve()
    latest: dict[str, tuple[Path, dict]] = {}
    for path in directory.glob("*.manifest.json"):
        try:
            manifest = load_manifest(path)
            kind = str(manifest["backup_type"])
            if kind not in latest or str(manifest["created_at"]) > str(
                latest[kind][1]["created_at"]
            ):
                latest[kind] = (path, manifest)
        except Exception:
            continue
    results = {kind: verify(item[0])[0] for kind, item in latest.items()}
    status = (
        "valid"
        if {"postgresql", "uploads"} <= set(results)
        and all(value == "valid" for value in results.values())
        else "invalid"
    )
    print(
        json.dumps({"status": status, "results": results}, sort_keys=True)
        if args.json
        else f"Latest backup verification: {status}"
    )
    return 0 if status == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
