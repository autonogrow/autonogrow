"""Create a verified uploads archive without following symbolic links. Dry-run by default."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.backup_common import (  # noqa: E402
    FORBIDDEN_NAMES,
    atomic_json,
    backup_set_id,
    manifest_for,
    safe_artifact_name,
    safe_output_directory,
)

from app.core.config import get_settings, get_uploads_dir  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.services.backup_record_service import record_backup_manifest  # noqa: E402


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--uploads-dir")
    value.add_argument("--output-dir")
    value.add_argument("--backup-set-id")
    value.add_argument("--apply", action="store_true")
    value.add_argument("--json", action="store_true")
    return value


def validate_tree(source: Path) -> int:
    count = 0
    for item in source.rglob("*"):
        if item.is_symlink():
            raise ValueError("Uploads contain a symbolic link")
        if item.name.lower() in FORBIDDEN_NAMES:
            raise ValueError("Uploads contain a forbidden secret-like path")
        if item.is_file():
            count += 1
    return count


def validate_archive(path: Path) -> int:
    count = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if (
                member.name.startswith(("/", "\\"))
                or ".." in parts
                or member.issym()
                or member.islnk()
            ):
                raise ValueError("Unsafe archive member")
            count += member.isfile()
    return count


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings = get_settings()
    source = Path(args.uploads_dir).resolve() if args.uploads_dir else get_uploads_dir()
    output = safe_output_directory(args.output_dir or settings.backup_dir or (ROOT / "backups"))
    set_id = backup_set_id(args.backup_set_id)
    artifact = output / safe_artifact_name(
        settings.app_env, settings.app_release_id, "uploads", "tar.gz"
    )
    try:
        files = validate_tree(source)
        if not args.apply:
            result = {
                "action": "uploads_backup",
                "apply": False,
                "artifact": artifact.name,
                "files": files,
                "backup_set_id": set_id,
            }
            print(
                json.dumps(result, sort_keys=True)
                if args.json
                else f"DRY-RUN: would archive {files} files"
            )
            return 0
        partial = artifact.with_name(artifact.name + ".partial")
        with tarfile.open(partial, "w:gz", dereference=False) as archive:
            archive.add(source, arcname="uploads", recursive=True)
        archived_files = validate_archive(partial)
        if archived_files != files:
            raise RuntimeError("Archive file count does not match source")
        os.chmod(partial, 0o600)
        partial.replace(artifact)
        manifest = manifest_for(
            artifact=artifact,
            kind="uploads",
            environment=settings.app_env,
            release=settings.app_release_id,
            set_id=set_id,
            extra={"files": files, "format": "tar.gz"},
        )
        manifest_path = artifact.with_name(artifact.name + ".manifest.json")
        atomic_json(manifest_path, manifest)
        metadata_status = "recorded"
        try:
            with SessionLocal() as db:
                record_backup_manifest(db, manifest)
                db.commit()
        except Exception:
            metadata_status = "warning"
        print(
            json.dumps(
                {
                    "status": "valid",
                    "artifact": artifact.name,
                    "manifest": manifest_path.name,
                    "metadata_persistence": metadata_status,
                },
                sort_keys=True,
            )
            if args.json
            else f"Created and verified {artifact.name}"
        )
        return 0
    except (OSError, tarfile.TarError, RuntimeError, ValueError) as exc:
        if "partial" in locals():
            partial.unlink(missing_ok=True)
        print(
            json.dumps({"status": "failed", "error": type(exc).__name__})
            if args.json
            else f"Backup failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
