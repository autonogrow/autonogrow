"""Copy a SQLite database and test Alembic only against the copy."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from alembic import command  # noqa: E402

from app.core.database import create_database_engine  # noqa: E402
from app.core.migration_state import (  # noqa: E402
    BASELINE_REVISION,
    alembic_config,
    inspect_database_migration_state,
)

CONFIRMATION = "STAMP-COPY-BASELINE"


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_database(source: Path, destination: Path) -> None:
    source_uri = f"file:{source.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_db:
        with sqlite3.connect(destination) as destination_db:
            source_db.backup(destination_db)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stamp-baseline", action="store_true")
    parser.add_argument("--confirm")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    if not source.is_file():
        print("La base de origen no existe o no es un fichero.", file=sys.stderr)
        return 2
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = (
        args.output.resolve()
        if args.output
        else source.with_name(f"{source.stem}.migration-test-{timestamp}{source.suffix}")
    )
    if destination == source or destination.exists():
        print("La salida debe ser una ruta nueva y distinta del origen.", file=sys.stderr)
        return 2

    original_digest = file_digest(source)
    copy_database(source, destination)
    database_url = f"sqlite:///{destination.as_posix()}"
    engine = create_database_engine(database_url)
    before = inspect_database_migration_state(engine)
    print(f"Copia de trabajo: {destination}")
    print(f"Estado inicial: {before.recommendation}")

    config = alembic_config()
    config.attributes["database_url"] = database_url
    if before.is_legacy:
        if not args.stamp_baseline or args.confirm != CONFIRMATION:
            print(
                f"La copia es heredada. Repetir con --stamp-baseline --confirm {CONFIRMATION}.",
                file=sys.stderr,
            )
            return 2
        if not before.is_baseline_compatible_legacy:
            print(
                "La copia heredada está incompleta; se requiere revisión manual.", file=sys.stderr
            )
            return 2
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")
    engine.dispose()

    after = inspect_database_migration_state(create_database_engine(database_url))
    source_unchanged = original_digest == file_digest(source)
    print(f"Estado final: {after.recommendation}")
    print(f"Origen sin cambios: {'sí' if source_unchanged else 'no'}")
    return 0 if after.is_at_head and source_unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
