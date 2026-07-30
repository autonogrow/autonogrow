"""Report database/Alembic state without applying any change."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_database_url  # noqa: E402
from app.core.database import create_database_engine  # noqa: E402
from app.core.migration_state import inspect_database_migration_state  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        help="URL a inspeccionar. Si se omite se usa Settings/DATABASE_URL.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database_url = args.database_url or get_database_url()
    state = inspect_database_migration_state(create_database_engine(database_url))
    print(f"Motor/ruta: {state.database}")
    print(f"Existe alembic_version: {'sí' if state.has_alembic_version else 'no'}")
    print(f"Revisión actual: {', '.join(state.current_revisions) or 'ninguna'}")
    print(f"Revisión head: {', '.join(state.head_revisions) or 'ninguna'}")
    print(f"Tablas esperadas: {', '.join(state.expected_tables)}")
    print(f"Tablas ausentes: {', '.join(state.missing_tables) or 'ninguna'}")
    print(f"Columnas críticas ausentes: {', '.join(state.missing_critical_columns) or 'ninguna'}")
    print(f"Parece vacía: {'sí' if state.is_empty else 'no'}")
    print(f"Parece heredada: {'sí' if state.is_legacy else 'no'}")
    print(f"Acción sugerida: {state.recommendation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
