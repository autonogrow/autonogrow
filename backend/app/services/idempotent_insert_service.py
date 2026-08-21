from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def insert_rows_ignore_conflicts(
    db: Session,
    model,
    rows: list[dict[str, Any]],
    *,
    index_elements: list[str] | None = None,
) -> None:
    """Insert missing defaults without turning a concurrent winner into a 500."""
    if not rows:
        return
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        postgresql_statement = postgresql_insert(model).values(rows).on_conflict_do_nothing(
            index_elements=index_elements
        )
        db.execute(postgresql_statement)
        return
    if dialect == "sqlite":
        sqlite_statement = sqlite_insert(model).values(rows).on_conflict_do_nothing(
            index_elements=index_elements
        )
        db.execute(sqlite_statement)
        return

    for values in rows:
        try:
            with db.begin_nested():
                db.add(model(**values))
                db.flush()
        except IntegrityError:
            continue
