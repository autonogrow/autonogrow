"""Create an atomic PostgreSQL custom-format backup. Dry-run unless --apply is used."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.backup_common import (  # noqa: E402
    atomic_json,
    backup_set_id,
    manifest_for,
    safe_artifact_name,
    safe_output_directory,
)

from app.core.config import get_database_url, get_settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.services.backup_record_service import record_backup_manifest  # noqa: E402


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--output-dir")
    value.add_argument("--backup-set-id")
    value.add_argument("--apply", action="store_true")
    value.add_argument("--json", action="store_true")
    return value


def pg_environment(database_url: str) -> tuple[dict[str, str], list[str]]:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL is required")
    environment = os.environ.copy()
    if url.password:
        environment["PGPASSWORD"] = url.password
    arguments = ["--dbname", url.database or "", "--host", url.host or "localhost"]
    if url.port:
        arguments += ["--port", str(url.port)]
    if url.username:
        arguments += ["--username", url.username]
    return environment, arguments


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings = get_settings()
    output = safe_output_directory(args.output_dir or settings.backup_dir or (ROOT / "backups"))
    set_id = backup_set_id(args.backup_set_id)
    artifact = output / safe_artifact_name(
        settings.app_env, settings.app_release_id, "postgresql", "dump"
    )
    plan = {
        "action": "postgresql_backup",
        "apply": args.apply,
        "artifact": artifact.name,
        "backup_set_id": set_id,
    }
    if not args.apply:
        print(
            json.dumps(plan, sort_keys=True)
            if args.json
            else f"DRY-RUN: would create {artifact.name}"
        )
        return 0
    partial = artifact.with_suffix(artifact.suffix + ".partial")
    try:
        environment, connection_args = pg_environment(get_database_url())
        subprocess.run(
            [
                settings.backup_pg_dump_path,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(partial),
                *connection_args,
            ],
            env=environment,
            check=True,
            timeout=settings.backup_timeout_seconds,
            capture_output=True,
        )
        if not partial.is_file() or partial.stat().st_size == 0:
            raise RuntimeError("pg_dump produced an empty artifact")
        subprocess.run(
            [settings.backup_pg_restore_path, "--list", str(partial)],
            check=True,
            timeout=120,
            capture_output=True,
        )
        os.chmod(partial, 0o600)
        partial.replace(artifact)
        manifest = manifest_for(
            artifact=artifact,
            kind="postgresql",
            environment=settings.app_env,
            release=settings.app_release_id,
            set_id=set_id,
            extra={"format": "pg_dump-custom"},
        )
        manifest_path = artifact.with_suffix(artifact.suffix + ".manifest.json")
        atomic_json(manifest_path, manifest)
        atomic_json(output / "backup-state.json", {"last_backup": manifest})
        try:
            with SessionLocal() as db:
                record_backup_manifest(db, manifest)
                db.commit()
        except Exception:
            plan["metadata_persistence"] = "warning"
        plan.update(
            {
                "status": "valid",
                "manifest": manifest_path.name,
                "size_bytes": manifest["size_bytes"],
            }
        )
        print(
            json.dumps(plan, sort_keys=True)
            if args.json
            else f"Created and verified {artifact.name}"
        )
        return 0
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
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
