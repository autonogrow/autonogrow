"""Create a consistent SQLite snapshot and a ZIP of uploads, without secrets."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_database_url, get_uploads_dir  # noqa: E402


def sqlite_path_from_config() -> Path:
    database_url = get_database_url()
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url == "sqlite:///:memory:":
        raise ValueError("El backup automático solo admite una base SQLite en disco")
    value = database_url.removeprefix(prefix)
    path = Path(value)
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def create_sqlite_snapshot(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"No existe la base SQLite: {source}")
    with sqlite3.connect(source, timeout=30) as connection:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("VACUUM INTO ?", (str(destination),))


def create_uploads_archive(uploads_dir: Path, destination: Path) -> int:
    count = 0
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        if not uploads_dir.exists():
            return count
        for source in sorted(uploads_dir.rglob("*")):
            if source.is_file():
                archive.write(source, Path("uploads") / source.relative_to(uploads_dir))
                count += 1
    return count


def apply_retention(output_dir: Path, keep: int) -> int:
    snapshots = sorted(output_dir.glob("autonogrow_*.sqlite3"), reverse=True)
    removed = 0
    for snapshot in snapshots[keep:]:
        timestamp = snapshot.stem.removeprefix("autonogrow_")
        archive = output_dir / f"uploads_{timestamp}.zip"
        snapshot.unlink(missing_ok=True)
        archive.unlink(missing_ok=True)
        removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backup consistente de SQLite y uploads de AutonoGrow"
    )
    parser.add_argument(
        "--database", type=Path, help="Ruta SQLite; por defecto usa DATABASE_URL/config"
    )
    parser.add_argument("--uploads", type=Path, help="Ruta de uploads; por defecto usa config")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "backups")
    parser.add_argument(
        "--keep", type=int, default=14, help="Número de juegos recientes que conservar"
    )
    args = parser.parse_args()
    if args.keep < 1:
        parser.error("--keep debe ser al menos 1")

    database = (args.database or sqlite_path_from_config()).resolve()
    uploads = (args.uploads or get_uploads_dir()).resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    snapshot = output_dir / f"autonogrow_{timestamp}.sqlite3"
    archive = output_dir / f"uploads_{timestamp}.zip"
    create_sqlite_snapshot(database, snapshot)
    file_count = create_uploads_archive(uploads, archive)
    removed = apply_retention(output_dir, args.keep)

    print(f"Backup SQLite creado: {snapshot.name}")
    print(f"Archivo de uploads creado: {archive.name} ({file_count} ficheros)")
    print(f"Juegos antiguos eliminados por retención: {removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
