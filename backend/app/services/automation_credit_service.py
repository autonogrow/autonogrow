import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import AutomationCreditTransaction, ConversationAutomationSettings

MAX_CREDIT_BALANCE = 10_000_000
CREDIT_TRANSACTION_TYPES = {
    "period_allowance_granted",
    "additional_credits_purchased",
    "automatic_message_consumed",
    "manual_adjustment",
    "refund",
    "correction",
    "migration_opening_balance",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )
    return normalized.isoformat().replace("+00:00", "Z")


def included_credits_remaining(settings: ConversationAutomationSettings) -> int:
    return max(
        int(settings.included_credits_per_period) - int(settings.included_credits_used),
        0,
    )


def total_credits_available(settings: ConversationAutomationSettings) -> int:
    return included_credits_remaining(settings) + max(int(settings.additional_credits_balance), 0)


def validate_credit_balances(settings: ConversationAutomationSettings) -> None:
    if settings.included_credits_per_period < 0:
        raise ValueError("Included credits cannot be negative")
    if not 0 <= settings.included_credits_used <= settings.included_credits_per_period:
        raise ValueError("Included credit usage is inconsistent")
    if settings.additional_credits_balance < 0:
        raise ValueError("Additional credit balance cannot be negative")
    if total_credits_available(settings) > MAX_CREDIT_BALANCE:
        raise ValueError("Credit balance exceeds the supported maximum")


def serialize_credit_summary(settings: ConversationAutomationSettings) -> dict[str, Any]:
    validate_credit_balances(settings)
    included_remaining = included_credits_remaining(settings)
    return {
        "business_id": settings.business_id,
        "included_credits_per_period": settings.included_credits_per_period,
        "included_credits_used": settings.included_credits_used,
        "included_credits_remaining": included_remaining,
        "additional_credits_balance": settings.additional_credits_balance,
        "total_available": included_remaining + settings.additional_credits_balance,
    }


def serialize_credit_transaction(item: AutomationCreditTransaction) -> dict[str, Any]:
    try:
        safe_metadata = json.loads(item.safe_metadata_json or "null")
    except (TypeError, ValueError):
        safe_metadata = None
    return {
        "id": item.id,
        "business_id": item.business_id,
        "transaction_type": item.transaction_type,
        "amount": item.amount,
        "included_delta": item.included_delta,
        "additional_delta": item.additional_delta,
        "included_balance_after": item.included_balance_after,
        "additional_balance_after": item.additional_balance_after,
        "total_balance_after": item.total_balance_after,
        "payment_amount": float(item.payment_amount) if item.payment_amount is not None else None,
        "payment_method": item.payment_method,
        "reason": item.reason,
        "external_reference": item.external_reference,
        "related_message_id": item.related_message_id,
        "period_started_at": _iso_utc(item.period_started_at),
        "owner_user_id": item.owner_user_id,
        "idempotency_key": item.idempotency_key,
        "safe_metadata": safe_metadata,
        "created_at": _iso_utc(item.created_at),
    }


def get_credit_transaction_by_idempotency(
    db: Session,
    *,
    business_id: int,
    idempotency_key: str,
) -> AutomationCreditTransaction | None:
    return (
        db.query(AutomationCreditTransaction)
        .filter(
            AutomationCreditTransaction.business_id == business_id,
            AutomationCreditTransaction.idempotency_key == idempotency_key,
        )
        .first()
    )


def lock_credit_wallet(
    db: Session,
    settings: ConversationAutomationSettings,
) -> ConversationAutomationSettings:
    """Lock one business wallet until the caller commits or rolls back."""

    if settings.id is None:
        db.flush()
    query = db.query(ConversationAutomationSettings).filter(
        ConversationAutomationSettings.id == settings.id
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.populate_existing().with_for_update()
    return query.one()


def record_credit_transaction(
    db: Session,
    *,
    settings: ConversationAutomationSettings,
    transaction_type: str,
    amount: int,
    included_delta: int = 0,
    additional_delta: int = 0,
    payment_amount: Decimal | float | None = None,
    payment_method: str | None = None,
    reason: str,
    external_reference: str | None = None,
    related_message_id: int | None = None,
    owner_user_id: int | None = None,
    idempotency_key: str | None = None,
    safe_metadata: dict[str, Any] | None = None,
) -> AutomationCreditTransaction:
    if transaction_type not in CREDIT_TRANSACTION_TYPES:
        raise ValueError("Invalid credit transaction type")
    validate_credit_balances(settings)
    item = AutomationCreditTransaction(
        business_id=settings.business_id,
        transaction_type=transaction_type,
        amount=amount,
        included_delta=included_delta,
        additional_delta=additional_delta,
        included_balance_after=included_credits_remaining(settings),
        additional_balance_after=settings.additional_credits_balance,
        total_balance_after=total_credits_available(settings),
        payment_amount=payment_amount,
        payment_method=payment_method,
        reason=reason,
        external_reference=external_reference,
        related_message_id=related_message_id,
        period_started_at=settings.period_started_at,
        owner_user_id=owner_user_id,
        idempotency_key=idempotency_key,
        safe_metadata_json=(
            json.dumps(safe_metadata, ensure_ascii=False, sort_keys=True) if safe_metadata else None
        ),
        created_at=utc_now(),
    )
    db.add(item)
    db.flush()
    return item


def grant_period_allowance(
    db: Session,
    *,
    settings: ConversationAutomationSettings,
    owner_user_id: int,
    reason: str,
    idempotency_key: str | None,
) -> AutomationCreditTransaction:
    settings = lock_credit_wallet(db, settings)
    old_remaining = included_credits_remaining(settings)
    settings.included_credits_used = 0
    settings.auto_used_current_period = 0
    settings.monthly_auto_limit = settings.included_credits_per_period
    settings.updated_at = utc_now()
    return record_credit_transaction(
        db,
        settings=settings,
        transaction_type="period_allowance_granted",
        amount=settings.included_credits_per_period,
        included_delta=settings.included_credits_per_period - old_remaining,
        reason=reason,
        owner_user_id=owner_user_id,
        idempotency_key=idempotency_key,
        safe_metadata={"expired_unused_included_credits": old_remaining},
    )


def purchase_additional_credits(
    db: Session,
    *,
    settings: ConversationAutomationSettings,
    credits: int,
    payment_amount: Decimal | float | None,
    payment_method: str | None,
    reason: str,
    external_reference: str | None,
    owner_user_id: int,
    idempotency_key: str,
) -> AutomationCreditTransaction:
    settings = lock_credit_wallet(db, settings)
    if credits <= 0:
        raise ValueError("Purchased credits must be positive")
    if total_credits_available(settings) + credits > MAX_CREDIT_BALANCE:
        raise ValueError("Credit balance exceeds the supported maximum")
    settings.additional_credits_balance += credits
    settings.updated_at = utc_now()
    return record_credit_transaction(
        db,
        settings=settings,
        transaction_type="additional_credits_purchased",
        amount=credits,
        additional_delta=credits,
        payment_amount=payment_amount,
        payment_method=payment_method,
        reason=reason,
        external_reference=external_reference,
        owner_user_id=owner_user_id,
        idempotency_key=idempotency_key,
    )


def adjust_credit_balances(
    db: Session,
    *,
    settings: ConversationAutomationSettings,
    included_delta: int,
    additional_delta: int,
    reason: str,
    owner_user_id: int,
    idempotency_key: str,
) -> AutomationCreditTransaction:
    settings = lock_credit_wallet(db, settings)
    old_included_remaining = included_credits_remaining(settings)
    new_included_remaining = old_included_remaining + included_delta
    new_additional = settings.additional_credits_balance + additional_delta
    if not 0 <= new_included_remaining <= settings.included_credits_per_period:
        raise ValueError("Included balance adjustment is outside the period allowance")
    if new_additional < 0:
        raise ValueError("Additional balance adjustment would make it negative")
    if new_included_remaining + new_additional > MAX_CREDIT_BALANCE:
        raise ValueError("Credit balance exceeds the supported maximum")
    settings.included_credits_used = settings.included_credits_per_period - new_included_remaining
    settings.additional_credits_balance = new_additional
    settings.updated_at = utc_now()
    return record_credit_transaction(
        db,
        settings=settings,
        transaction_type="manual_adjustment",
        amount=included_delta + additional_delta,
        included_delta=included_delta,
        additional_delta=additional_delta,
        reason=reason,
        owner_user_id=owner_user_id,
        idempotency_key=idempotency_key,
    )


def consume_automation_credit(
    db: Session,
    *,
    settings: ConversationAutomationSettings,
    related_message_id: int,
) -> tuple[bool, AutomationCreditTransaction | None]:
    existing = (
        db.query(AutomationCreditTransaction)
        .filter(AutomationCreditTransaction.related_message_id == related_message_id)
        .first()
    )
    if existing is not None:
        return False, existing
    settings = lock_credit_wallet(db, settings)
    existing = (
        db.query(AutomationCreditTransaction)
        .filter(AutomationCreditTransaction.related_message_id == related_message_id)
        .first()
    )
    if existing is not None:
        return False, existing
    included_delta = 0
    additional_delta = 0
    if included_credits_remaining(settings) > 0:
        settings.included_credits_used += 1
        included_delta = -1
    elif settings.additional_credits_balance > 0:
        settings.additional_credits_balance -= 1
        additional_delta = -1
    else:
        return False, None
    settings.auto_used_current_period += 1
    settings.updated_at = utc_now()
    item = record_credit_transaction(
        db,
        settings=settings,
        transaction_type="automatic_message_consumed",
        amount=1,
        included_delta=included_delta,
        additional_delta=additional_delta,
        reason="Mensaje automático encolado",
        related_message_id=related_message_id,
        idempotency_key=f"automatic-message:{related_message_id}",
    )
    return True, item
