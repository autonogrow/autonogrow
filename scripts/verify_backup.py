"""Verify backup checksums and archive structure without restoring data."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.backup_common import load_manifest, sha256_file  # noqa: E402
from scripts.backup_uploads import validate_archive  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.services.backup_record_service import record_backup_verification  # noqa: E402


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("manifest", type=Path)
    value.add_argument("--json", action="store_true")
    return value


def verify(manifest_path: Path) -> tuple[str, list[str]]:
    issues: list[str] = []
    manifest = load_manifest(manifest_path.resolve())
    artifact = (manifest_path.resolve().parent / str(manifest.get("artifact_name", ""))).resolve()
    if artifact.parent != manifest_path.resolve().parent:
        return "invalid", ["artifact_path"]
    if not artifact.is_file() or artifact.stat().st_size <= 0:
        return "invalid", ["artifact_missing"]
    if artifact.stat().st_size != manifest.get("size_bytes"):
        issues.append("size_mismatch")
    if sha256_file(artifact) != manifest.get("sha256"):
        issues.append("checksum_mismatch")
    if issues:
        return "invalid", issues
    kind = manifest.get("backup_type")
    try:
        if kind == "postgresql":
            subprocess.run(
                [get_settings().backup_pg_restore_path, "--list", str(artifact)],
                check=True,
                timeout=120,
                capture_output=True,
            )
        elif kind == "uploads":
            validate_archive(artifact)
        else:
            return "invalid", ["unknown_type"]
    except (OSError, subprocess.SubprocessError, tarfile.TarError, ValueError):
        return "invalid", ["structure_invalid"]
    return "valid", []


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        status, issues = verify(args.manifest)
    except (OSError, ValueError, json.JSONDecodeError):
        status, issues = "invalid", ["manifest_invalid"]
    payload = {"status": status, "issues": issues, "manifest": args.manifest.name}
    try:
        manifest = load_manifest(args.manifest.resolve())
        with SessionLocal() as db:
            record_backup_verification(
                db, artifact_name=str(manifest["artifact_name"]), status=status
            )
            db.commit()
    except Exception:
        payload["metadata_persistence"] = "warning"
    print(json.dumps(payload, sort_keys=True) if args.json else f"Backup verification: {status}")
    return 0 if status == "valid" else 2 if status == "warning" else 1


if __name__ == "__main__":
    raise SystemExit(main())
