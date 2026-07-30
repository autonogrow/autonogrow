"""Report aggregate pg_stat_statements timings without emitting query text."""

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
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    engine = create_engine(get_database_url())
    try:
        with engine.connect() as connection:
            installed = connection.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_stat_statements')"
                )
            ).scalar_one()
            if not installed:
                payload = {
                    "status": "warning",
                    "reason": "pg_stat_statements_not_installed",
                    "queries": [],
                }
                print(
                    json.dumps(payload)
                    if args.json
                    else "WARNING: pg_stat_statements is not installed"
                )
                return 2
            rows = (
                connection.execute(
                    text(
                        "SELECT queryid, calls, total_exec_time, mean_exec_time, rows FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT :limit"
                    ),
                    {"limit": args.limit},
                )
                .mappings()
                .all()
            )
        payload = {
            "status": "ok",
            "query_text_included": False,
            "queries": [dict(row) for row in rows],
        }
        print(
            json.dumps(payload, default=str) if args.json else f"Slow query aggregates: {len(rows)}"
        )
        return 0
    except Exception as exc:
        print(f"Slow query report failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
