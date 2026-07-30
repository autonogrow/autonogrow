"""Run bounded read-only PostgreSQL health diagnostics without printing SQL text."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_database_url  # noqa: E402


def collect() -> dict:
    url = get_database_url()
    if make_url(url).get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL is required")
    engine = create_engine(url)
    statements = {
        "server_version": "SHOW server_version",
        "database_size_bytes": "SELECT pg_database_size(current_database())",
        "connections": "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()",
        "max_connections": "SHOW max_connections",
        "idle_transactions": "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='idle in transaction'",
        "blocked_sessions": "SELECT count(*) FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid)) > 0",
        "long_queries": "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='active' AND query_start < now() - interval '60 seconds' AND pid <> pg_backend_pid()",
        "dead_tuples": "SELECT COALESCE(sum(n_dead_tup),0) FROM pg_stat_user_tables",
        "user_tables": "SELECT count(*) FROM pg_stat_user_tables",
    }
    try:
        with engine.connect() as connection:
            values = {
                key: connection.execute(text(sql)).scalar_one() for key, sql in statements.items()
            }
        return {"status": "ok", **values}
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = collect()
        print(
            json.dumps(result, sort_keys=True, default=str)
            if args.json
            else "PostgreSQL health check: ok"
        )
        return 0
    except Exception as exc:
        print(
            json.dumps({"status": "error", "error": type(exc).__name__})
            if args.json
            else f"PostgreSQL health check failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
