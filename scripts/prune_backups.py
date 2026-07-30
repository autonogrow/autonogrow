"""Plan or apply confined retention of complete backup sets. Dry-run by default."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.backup_common import load_manifest, safe_output_directory  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--backup-dir")
    value.add_argument("--retention-days", type=int)
    value.add_argument("--minimum-count", type=int)
    value.add_argument("--apply", action="store_true")
    value.add_argument("--json", action="store_true")
    return value


def plan_prune(directory: Path, retention_days: int, minimum_count: int) -> list[Path]:
    records: list[tuple[datetime, str, bool, list[Path]]] = []
    grouped: dict[str, list[tuple[Path, dict]]] = {}
    for path in directory.glob("*.manifest.json"):
        try:
            manifest = load_manifest(path)
            grouped.setdefault(str(manifest["backup_set_id"]), []).append((path, manifest))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    for set_id, entries in grouped.items():
        kinds = {str(item[1].get("backup_type")) for item in entries}
        if kinds != {"postgresql", "uploads"} or any(
            item[1].get("status") != "valid" for item in entries
        ):
            continue
        created = min(
            datetime.fromisoformat(str(item[1]["created_at"]).replace("Z", "+00:00"))
            for item in entries
        )
        protected = any(bool(item[1].get("protected")) for item in entries)
        files: list[Path] = []
        for manifest_path, manifest in entries:
            artifact = (directory / str(manifest["artifact_name"])).resolve()
            if artifact.parent == directory:
                files.extend((artifact, manifest_path.resolve()))
        records.append((created, set_id, protected, files))
    records.sort(key=lambda item: item[0], reverse=True)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removable: list[Path] = []
    for index, (created, _set_id, protected, files) in enumerate(records):
        if index < minimum_count or protected or created >= cutoff:
            continue
        removable.extend(files)
    return removable


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings = get_settings()
    directory = safe_output_directory(args.backup_dir or settings.backup_dir or (ROOT / "backups"))
    retention = args.retention_days or settings.backup_retention_days
    minimum = args.minimum_count or settings.backup_minimum_count
    if retention < 1 or minimum < 1:
        print("Invalid retention policy", file=sys.stderr)
        return 2
    files = plan_prune(directory, retention, minimum)
    if args.apply:
        for path in files:
            resolved = path.resolve()
            if resolved.parent != directory:
                raise RuntimeError("Refusing path outside backup directory")
            resolved.unlink(missing_ok=True)
    payload = {"apply": args.apply, "files": [path.name for path in files], "count": len(files)}
    print(
        json.dumps(payload, sort_keys=True)
        if args.json
        else f"{'Deleted' if args.apply else 'Would delete'} {len(files)} files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
