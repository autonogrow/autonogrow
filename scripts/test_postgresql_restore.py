"""Restore a PostgreSQL backup into an explicitly temporary isolated database."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.backup_common import load_manifest, sha256_file  # noqa: E402

from app.core.config import get_database_url, get_settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.migration_state import head_revisions  # noqa: E402
from app.services.backup_record_service import record_backup_verification  # noqa: E402

TEMP_DATABASE = re.compile(r"autonogrow_restore_[a-z0-9_]{4,48}\Z")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("manifest", type=Path)
    value.add_argument("--apply", action="store_true")
    value.add_argument("--keep-temporary-database", action="store_true")
    value.add_argument("--json", action="store_true")
    return value


def safe_target_url() -> tuple[object, str]:
    raw = os.environ.get("RESTORE_TEST_DATABASE_URL", "")
    if not raw:
        raise ValueError("RESTORE_TEST_DATABASE_URL is required")
    target = make_url(raw)
    source = make_url(get_database_url())
    if target.get_backend_name() != "postgresql" or not TEMP_DATABASE.fullmatch(
        target.database or ""
    ):
        raise ValueError("Destination database is not explicitly temporary")
    if target.render_as_string(hide_password=True) == source.render_as_string(hide_password=True):
        raise ValueError("Destination must differ from the application database")
    return target, raw


def pg_env(url) -> dict[str, str]:
    environment = os.environ.copy()
    if url.password:
        environment["PGPASSWORD"] = url.password
    return environment


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings = get_settings()
    try:
        manifest = load_manifest(args.manifest.resolve())
        if manifest.get("backup_type") != "postgresql":
            raise ValueError("PostgreSQL manifest required")
        artifact = (args.manifest.resolve().parent / str(manifest["artifact_name"])).resolve()
        if (
            artifact.parent != args.manifest.resolve().parent
            or sha256_file(artifact) != manifest["sha256"]
        ):
            raise ValueError("Backup checksum mismatch")
        target, target_raw = safe_target_url()
        if not args.apply:
            payload = {"status": "dry_run", "database": target.database, "artifact": artifact.name}
            print(
                json.dumps(payload, sort_keys=True)
                if args.json
                else f"DRY-RUN: would restore {artifact.name} into {target.database}"
            )
            return 0
        admin_url = target.set(database="postgres")
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        destination = create_engine(target_raw)
        created = False
        try:
            with admin.connect() as connection:
                exists = connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": target.database}
                ).scalar()
                if exists:
                    raise ValueError("Temporary destination already exists")
                connection.exec_driver_sql(f'CREATE DATABASE "{target.database}"')
                created = True
            command = [
                settings.backup_pg_restore_path,
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                target.database or "",
                "--host",
                target.host or "localhost",
            ]
            if target.port:
                command += ["--port", str(target.port)]
            if target.username:
                command += ["--username", target.username]
            command.append(str(artifact))
            subprocess.run(
                command,
                env=pg_env(target),
                check=True,
                timeout=settings.backup_timeout_seconds,
                capture_output=True,
            )
            inspector = inspect(destination)
            tables = set(inspector.get_table_names())
            required = {
                "businesses",
                "users",
                "bookings",
                "business_channel_integrations",
                "alembic_version",
            }
            if not required <= tables:
                raise RuntimeError("Restored schema is incomplete")
            with destination.connect() as connection:
                current = tuple(sorted(MigrationContext.configure(connection).get_current_heads()))
                counts = {
                    "businesses": connection.execute(
                        text("SELECT count(*) FROM businesses")
                    ).scalar_one(),
                    "users": connection.execute(text("SELECT count(*) FROM users")).scalar_one(),
                    "bookings": connection.execute(
                        text("SELECT count(*) FROM bookings")
                    ).scalar_one(),
                    "business_channel_integrations": connection.execute(
                        text("SELECT count(*) FROM business_channel_integrations")
                    ).scalar_one(),
                }
                ciphertext_rows = connection.execute(
                    text(
                        "SELECT count(*) FROM business_channel_integrations WHERE encrypted_access_token IS NOT NULL AND encryption_key_version IS NOT NULL"
                    )
                ).scalar_one()
            status = "valid" if set(current) == set(head_revisions()) else "warning"
            payload = {
                "status": status,
                "database": target.database,
                "current_revisions": current,
                "counts": counts,
                "ciphertext_rows": ciphertext_rows,
            }
            try:
                with SessionLocal() as db:
                    record_backup_verification(
                        db,
                        artifact_name=str(manifest["artifact_name"]),
                        status=status,
                        restore_test=True,
                    )
                    db.commit()
            except Exception:
                payload["metadata_persistence"] = "warning"
            print(json.dumps(payload, sort_keys=True) if args.json else f"Restore test: {status}")
            return 0 if status == "valid" else 2
        finally:
            destination.dispose()
            if created and not args.keep_temporary_database:
                with admin.connect() as connection:
                    connection.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid <> pg_backend_pid()"
                        ),
                        {"name": target.database},
                    )
                    connection.exec_driver_sql(f'DROP DATABASE "{target.database}"')
            admin.dispose()
    except (OSError, KeyError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(
            json.dumps({"status": "invalid", "error": type(exc).__name__})
            if args.json
            else f"Restore test failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
