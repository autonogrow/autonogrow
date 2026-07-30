"""Conservative wrapper around the approved AutonoGrow migration operations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from alembic import command  # noqa: E402

from app.core.config import get_database_url  # noqa: E402
from app.core.database import create_database_engine  # noqa: E402
from app.core.migration_state import (  # noqa: E402
    BASELINE_REVISION,
    alembic_config,
    inspect_database_migration_state,
)

CONFIRMATION = "STAMP-BASELINE"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("status", "validate", "history", "upgrade", "stamp-baseline"),
    )
    parser.add_argument("--database-url")
    parser.add_argument(
        "--confirm",
        help=f"Para stamp-baseline debe ser exactamente {CONFIRMATION}.",
    )
    return parser.parse_args()


def config_for(database_url: str):
    config = alembic_config()
    config.attributes["database_url"] = database_url
    return config


def main() -> int:
    args = parse_args()
    database_url = args.database_url or get_database_url()
    config = config_for(database_url)
    if args.command == "history":
        command.history(config, verbose=True)
        return 0

    state = inspect_database_migration_state(create_database_engine(database_url))
    if args.command == "status":
        print(f"Base: {state.database}")
        print(f"Actual: {', '.join(state.current_revisions) or 'ninguna'}")
        print(f"Head: {', '.join(state.head_revisions) or 'ninguna'}")
        print(f"Acción sugerida: {state.recommendation}")
        return 0
    if args.command == "validate":
        print("Base en head" if state.is_at_head else state.recommendation)
        return 0 if state.is_at_head else 1
    if args.command == "upgrade":
        if state.is_legacy:
            print(
                "Rechazado: una base heredada debe diagnosticarse y marcarse "
                "explícitamente antes del upgrade.",
                file=sys.stderr,
            )
            return 2
        command.upgrade(config, "head")
        return 0

    if args.confirm != CONFIRMATION:
        print(
            f"Rechazado: use --confirm {CONFIRMATION} tras validar backup y esquema.",
            file=sys.stderr,
        )
        return 2
    if state.is_empty:
        print("Rechazado: una base vacía debe ejecutar upgrade head.", file=sys.stderr)
        return 2
    if not state.is_legacy:
        print("Rechazado: la base ya tiene historial Alembic.", file=sys.stderr)
        return 2
    if not state.is_baseline_compatible_legacy:
        print("Rechazado: la base heredada está incompleta.", file=sys.stderr)
        return 2
    command.stamp(config, BASELINE_REVISION)
    print(f"Baseline aplicada: {BASELINE_REVISION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
