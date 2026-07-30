from __future__ import annotations

import builtins
from dataclasses import dataclass

from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, TimeoutError
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class DatabaseErrorClassification:
    code: str
    retryable: bool
    safe_message: str


POSTGRESQL_ERROR_CODES = {
    "40P01": DatabaseErrorClassification(
        "deadlock_detected", True, "Database transaction was selected for retry"
    ),
    "40001": DatabaseErrorClassification(
        "serialization_failure", True, "Database transaction must be retried"
    ),
    "55P03": DatabaseErrorClassification("lock_timeout", True, "Database row is temporarily busy"),
    "57014": DatabaseErrorClassification(
        "database_statement_timeout", True, "Database statement exceeded its time limit"
    ),
    "23505": DatabaseErrorClassification(
        "unique_conflict", False, "Database uniqueness rule rejected the operation"
    ),
    "23503": DatabaseErrorClassification(
        "foreign_key_violation", False, "Database relationship rule rejected the operation"
    ),
    "23514": DatabaseErrorClassification(
        "integrity_violation", False, "Database integrity rule rejected the operation"
    ),
}


def database_sqlstate(exc: BaseException) -> str | None:
    original = getattr(exc, "orig", None)
    value = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return str(value) if value else None


def classify_database_error(exc: BaseException) -> DatabaseErrorClassification:
    """Map database failures to safe operational categories without leaking SQL or values."""

    sqlstate = database_sqlstate(exc)
    if sqlstate in POSTGRESQL_ERROR_CODES:
        return POSTGRESQL_ERROR_CODES[sqlstate]
    original = getattr(exc, "orig", None)
    if isinstance(original, builtins.TimeoutError):
        return DatabaseErrorClassification(
            "connection_timeout", True, "Database connection attempt exceeded its time limit"
        )
    if isinstance(exc, TimeoutError):
        return DatabaseErrorClassification(
            "pool_timeout", True, "No database connection became available in time"
        )
    if isinstance(exc, OperationalError):
        return DatabaseErrorClassification(
            "database_unavailable", True, "Database is temporarily unavailable"
        )
    if isinstance(exc, IntegrityError):
        return DatabaseErrorClassification(
            "integrity_violation", False, "Database integrity rule rejected the operation"
        )
    if isinstance(exc, DBAPIError):
        return DatabaseErrorClassification(
            "database_operation_failure",
            bool(exc.connection_invalidated),
            "Database operation failed",
        )
    return DatabaseErrorClassification(
        "database_unknown_failure", False, "Unexpected database operation failure"
    )


def report_database_incident(
    db: Session,
    exc: BaseException,
    *,
    operation: str,
    business_id: int | None = None,
) -> DatabaseErrorClassification:
    """Persist a safe database incident without including SQL, parameters, or connection data."""

    from app.services.incident_service import report_incident

    classification = classify_database_error(exc)
    severity = (
        "critical"
        if classification.code in {"database_unavailable", "connection_timeout", "pool_timeout"}
        else "high"
    )
    report_incident(
        db,
        category=classification.code,
        severity=severity,
        business_id=business_id,
        channel=None,
        provider="database",
        provider_error_code=database_sqlstate(exc),
        operation=operation,
        safe_details={"retryable": classification.retryable},
    )
    return classification
