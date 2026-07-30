"""Read PostgreSQL index usage and table dead-tuple aggregates; never changes indexes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_database_url  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    engine = create_engine(get_database_url())
    try:
        with engine.connect() as connection:
            unused = (
                connection.execute(
                    text(
                        "SELECT schemaname, relname AS table_name, indexrelname AS index_name, idx_scan, pg_relation_size(indexrelid) AS size_bytes FROM pg_stat_user_indexes WHERE idx_scan=0 ORDER BY pg_relation_size(indexrelid) DESC LIMIT :limit"
                    ),
                    {"limit": args.limit},
                )
                .mappings()
                .all()
            )
            dead = (
                connection.execute(
                    text(
                        "SELECT schemaname, relname AS table_name, n_live_tup, n_dead_tup, last_autovacuum FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT :limit"
                    ),
                    {"limit": args.limit},
                )
                .mappings()
                .all()
            )
        payload = {
            "status": "ok",
            "automatic_changes": False,
            "unused_indexes": [dict(row) for row in unused],
            "table_health": [dict(row) for row in dead],
        }
        print(
            json.dumps(payload, default=str)
            if args.json
            else f"Index candidates: {len(unused)}; tables: {len(dead)}"
        )
        return 0
    except Exception as exc:
        print(f"Index health failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
