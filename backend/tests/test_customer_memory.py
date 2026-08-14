from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.core.security import require_business_access
from app.models import (
    AuditLog,
    Booking,
    Business,
    BusinessService,
    BusinessUser,
    Customer,
    CustomerMemoryItem,
    CustomerOpportunity,
    User,
)
from app.routers.customer_memory import (
    create_customer_memory,
    delete_customer_memory,
    get_customer_memory_summary,
    list_customer_memory,
    mark_customer_memory_obsolete,
    supersede_customer_memory,
    update_customer_memory,
)
from app.routers.growth_opportunities import serialize_opportunity_detail
from app.schemas.customer_memory import (
    CustomerMemoryCreate,
    CustomerMemoryReplacement,
    CustomerMemoryUpdate,
)
from app.services.customer_memory_service import (
    CustomerMemoryService,
    validate_memory_content,
)
from app.services.growth_opportunity_service import GrowthOpportunityService

NOW = datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    from app.core.database import Base

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def records(db: Session) -> dict:
    business_a = Business(slug="memory-a", name="Memory A", status="active")
    business_b = Business(slug="memory-b", name="Memory B", status="active")
    owner = User(email="memory-owner@test.local", is_owner=True)
    admin = User(email="memory-admin@test.local")
    staff = User(email="memory-staff@test.local")
    outsider = User(email="memory-outsider@test.local")
    db.add_all((business_a, business_b, owner, admin, staff, outsider))
    db.flush()
    db.add_all(
        (
            BusinessUser(
                business_id=business_a.id,
                user_id=admin.id,
                role="business_admin",
                active=True,
            ),
            BusinessUser(
                business_id=business_a.id,
                user_id=staff.id,
                role="business_staff",
                active=True,
            ),
            BusinessUser(
                business_id=business_b.id,
                user_id=outsider.id,
                role="business_admin",
                active=True,
            ),
        )
    )
    customer_a = Customer(business_id=business_a.id, name="Ana", phone="+34600111111")
    customer_empty = Customer(business_id=business_a.id, name="Eva", phone="+34600222222")
    customer_b = Customer(business_id=business_b.id, name="Bea", phone="+34600111111")
    service_a = BusinessService(
        business_id=business_a.id,
        name="Manicura",
        duration_minutes=45,
        follow_up_enabled=True,
        follow_up_interval_days=30,
        follow_up_window_days=5,
    )
    service_a2 = BusinessService(
        business_id=business_a.id,
        name="Pedicura",
        duration_minutes=60,
        follow_up_enabled=False,
    )
    service_b = BusinessService(
        business_id=business_b.id,
        name="Revisión",
        duration_minutes=60,
        follow_up_enabled=False,
    )
    db.add_all((customer_a, customer_empty, customer_b, service_a, service_a2, service_b))
    db.commit()
    return {
        "a": business_a,
        "b": business_b,
        "owner": owner,
        "admin": admin,
        "staff": staff,
        "outsider": outsider,
        "customer_a": customer_a,
        "customer_empty": customer_empty,
        "customer_b": customer_b,
        "service_a": service_a,
        "service_a2": service_a2,
        "service_b": service_b,
    }


def request(path: str = "/api/admin/businesses/memory-a/customers/1/memory") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": ("testclient", 50000),
        }
    )


def completed_booking(
    db: Session,
    *,
    business: Business,
    customer: Customer,
    service: BusinessService,
    occurred_at: datetime,
    status: str = "completed",
    recurrence: bool = False,
) -> Booking:
    naive = occurred_at.astimezone(timezone.utc).replace(tzinfo=None)
    row = Booking(
        business_id=business.id,
        customer_id=customer.id,
        service_id=service.id,
        service_name=service.name,
        duration_minutes=service.duration_minutes,
        start_datetime=naive - timedelta(minutes=service.duration_minutes or 30),
        end_datetime=naive,
        preferred_date=naive.date().isoformat(),
        preferred_time=naive.strftime("%H:%M"),
        status=status,
        follow_up_enabled_snapshot=recurrence,
        follow_up_interval_days_snapshot=30 if recurrence else None,
        follow_up_window_days_snapshot=5 if recurrence else None,
    )
    db.add(row)
    db.commit()
    return row


def add_memory(
    db: Session,
    records: dict,
    *,
    value: str = "Prefiere tardes",
    customer: Customer | None = None,
    now: datetime = NOW,
    expires_at: datetime | None = None,
) -> CustomerMemoryItem:
    row, _ = CustomerMemoryService(db, now=now).create_manual(
        business_id=(customer or records["customer_a"]).business_id,
        customer_id=(customer or records["customer_a"]).id,
        category="availability_preference",
        key="preferred_time",
        value=value,
        created_by_user_id=records["admin"].id,
        expires_at=expires_at,
    )
    db.commit()
    return row


def test_memory_crud_supersede_delete_and_content_safe_audit(
    db: Session, records: dict
) -> None:
    created = create_customer_memory(
        "memory-a",
        records["customer_a"].id,
        CustomerMemoryCreate(
            category="availability_preference",
            key="preferred_time",
            value="Prefiere tardes",
            is_sensitive=True,
        ),
        request(),
        records["staff"],
        db,
    )["memory"]
    assert created["source_type"] == "manual"
    assert created["confidence"] == 1.0
    assert created["status"] == "active"

    updated = update_customer_memory(
        "memory-a",
        created["id"],
        CustomerMemoryUpdate(value="Prefiere viernes por la tarde"),
        request(),
        records["staff"],
        db,
    )["memory"]
    assert updated["value"] == "Prefiere viernes por la tarde"

    replacement = supersede_customer_memory(
        "memory-a",
        created["id"],
        CustomerMemoryReplacement(value="Prefiere mañanas"),
        request(),
        records["admin"],
        db,
    )["memory"]
    previous = db.get(CustomerMemoryItem, created["id"])
    assert previous is not None
    assert previous.status == "superseded"
    assert previous.superseded_by_id == replacement["id"]
    assert previous.superseded_at is not None

    listed = list_customer_memory(
        "memory-a", records["customer_a"].id, "all", db
    )["items"]
    assert {item["status"] for item in listed} == {"active", "superseded"}

    delete_customer_memory(
        "memory-a", replacement["id"], request(), records["staff"], db
    )
    deleted = db.get(CustomerMemoryItem, replacement["id"])
    assert deleted is not None and deleted.status == "deleted" and deleted.deleted_at
    assert list_customer_memory(
        "memory-a", records["customer_a"].id, "active", db
    )["items"] == []

    logs = db.query(AuditLog).filter(AuditLog.resource_type == "customer_memory_item").all()
    assert {log.action for log in logs} >= {
        "customer_memory_created",
        "customer_memory_updated",
        "customer_memory_superseded",
        "customer_memory_deleted",
    }
    assert all("Prefiere" not in (log.metadata_json or "") for log in logs)
    changed = next(log for log in logs if log.action == "customer_memory_updated")
    assert json.loads(changed.metadata_json or "{}")["changed_fields"] == ["value"]


def test_expiration_obsolete_history_and_customer_cascade(
    db: Session, records: dict
) -> None:
    expired = add_memory(
        db,
        records,
        value="Solo tardes durante agosto",
        now=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    service = CustomerMemoryService(db, now=NOW + timedelta(days=2))
    assert service.list_items(
        business_id=records["a"].id,
        customer_id=records["customer_a"].id,
        status="active",
    ) == []
    db.commit()
    assert expired.status == "expired"
    assert service.list_items(
        business_id=records["a"].id,
        customer_id=records["customer_a"].id,
        status="expired",
    ) == [expired]

    active = add_memory(db, records, value="Prefiere primera hora")
    mark_customer_memory_obsolete(
        "memory-a", active.id, request(), records["staff"], db
    )
    assert active.status == "superseded" and active.superseded_by_id is None

    customer_id = records["customer_a"].id
    db.delete(records["customer_a"])
    db.commit()
    assert db.query(CustomerMemoryItem).filter_by(customer_id=customer_id).count() == 0


def test_tenant_permissions_and_cross_ids_are_rejected(db: Session, records: dict) -> None:
    assert require_business_access("memory-a", records["staff"], db) == records["staff"]
    assert require_business_access("memory-a", records["owner"], db) == records["owner"]
    with pytest.raises(HTTPException) as denied:
        require_business_access("memory-a", records["outsider"], db)
    assert denied.value.status_code == 403

    with pytest.raises(HTTPException) as cross_customer:
        create_customer_memory(
            "memory-a",
            records["customer_b"].id,
            CustomerMemoryCreate(category="preference", value="Cruce inválido"),
            request(),
            records["admin"],
            db,
        )
    assert cross_customer.value.status_code == 404

    foreign = add_memory(db, records, customer=records["customer_b"], value="Solo B")
    with pytest.raises(HTTPException) as cross_memory:
        delete_customer_memory(
            "memory-a", foreign.id, request(), records["admin"], db
        )
    assert cross_memory.value.status_code == 404
    summary = get_customer_memory_summary(
        "memory-a", records["customer_empty"].id, db
    )
    assert summary["explicit"] == []
    assert summary["derived"]["visit_count"] == 0


def test_secret_card_and_database_constraints(db: Session, records: dict) -> None:
    for unsafe in (
        "password: super-secret",
        "API key abcdef",
        "token: abcdef",
        "Tarjeta 4111 1111 1111 1111",
        "-----BEGIN PRIVATE KEY-----",
    ):
        with pytest.raises(ValueError):
            validate_memory_content(unsafe)
    assert validate_memory_content("Prefiere tonos naturales") == "Prefiere tonos naturales"

    db.add(
        CustomerMemoryItem(
            business_id=records["a"].id,
            customer_id=records["customer_a"].id,
            category="medical_profile",
            key="diagnosis",
            value="No permitido",
            value_type="text",
            source_type="manual",
            confidence=1.0,
            status="active",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_derived_summary_uses_completed_visits_median_tie_and_recurrence(
    db: Session, records: dict
) -> None:
    dates = [
        datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        datetime(2026, 1, 21, 12, tzinfo=timezone.utc),
        datetime(2026, 2, 10, 12, tzinfo=timezone.utc),
        datetime(2026, 5, 31, 12, tzinfo=timezone.utc),
    ]
    completed_booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        occurred_at=dates[0],
        recurrence=True,
    )
    completed_booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        occurred_at=dates[1],
    )
    completed_booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a2"],
        occurred_at=dates[2],
    )
    completed_booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a2"],
        occurred_at=dates[3],
    )
    completed_booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        occurred_at=NOW,
        status="cancelled",
    )
    completed_booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        occurred_at=NOW,
        status="no_show",
    )
    completed_booking(
        db,
        business=records["b"],
        customer=records["customer_b"],
        service=records["service_b"],
        occurred_at=NOW,
    )

    derived = CustomerMemoryService(db, now=NOW).summary(
        business_id=records["a"].id, customer_id=records["customer_a"].id
    )["derived"]
    assert derived["visit_count"] == 4
    assert derived["last_service"]["name"] == "Pedicura"
    assert derived["most_frequent_service"] == {
        "id": records["service_a2"].id,
        "name": "Pedicura",
        "visit_count": 2,
    }
    assert derived["observed_return_interval_days"] == 20
    assert derived["configured_recurrence"]["interval_days"] == 30
    assert derived["return_interval_priority"] == "configured_recurrence"


def test_interval_requires_four_visits_and_one_visit_is_precise(
    db: Session, records: dict
) -> None:
    completed_booking(
        db,
        business=records["a"],
        customer=records["customer_empty"],
        service=records["service_a"],
        occurred_at=NOW - timedelta(days=30),
    )
    summary = CustomerMemoryService(db, now=NOW).summary(
        business_id=records["a"].id, customer_id=records["customer_empty"].id
    )["derived"]
    assert summary["visit_count"] == 1
    assert summary["last_service"]["name"] == "Manicura"
    assert summary["most_frequent_service"]["name"] == "Manicura"
    assert summary["observed_return_interval_days"] is None
    assert summary["return_interval_priority"] is None

    for days_ago in (20, 10):
        completed_booking(
            db,
            business=records["a"],
            customer=records["customer_empty"],
            service=records["service_a"],
            occurred_at=NOW - timedelta(days=days_ago),
        )
    summary = CustomerMemoryService(db, now=NOW).summary(
        business_id=records["a"].id, customer_id=records["customer_empty"].id
    )["derived"]
    assert summary["visit_count"] == 3
    assert summary["observed_return_interval_days"] is None


def test_growth_detail_reads_active_memory_without_changing_detection(
    db: Session, records: dict
) -> None:
    source = completed_booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        occurred_at=NOW - timedelta(days=25),
        recurrence=True,
    )
    memory = add_memory(db, records)
    add_memory(db, records, customer=records["customer_b"], value="Dato de B")

    GrowthOpportunityService(db, now=NOW).evaluate_business(records["a"].id)
    db.commit()
    opportunity = db.query(CustomerOpportunity).one()
    assert opportunity.type == "service_due"
    assert opportunity.source_booking_id == source.id
    before = db.query(CustomerOpportunity).count()

    detail = serialize_opportunity_detail(
        db, opportunity, include_full_customer_context=True
    )
    assert detail["customer_context"]["explicit"] == [
        {
            "id": memory.id,
            "category": "availability_preference",
            "value": "Prefiere tardes",
            "is_sensitive": False,
        }
    ]
    assert "Dato de B" not in json.dumps(detail, ensure_ascii=False)

    CustomerMemoryService(db, now=NOW).soft_delete(memory)
    db.commit()
    detail = serialize_opportunity_detail(
        db, opportunity, include_full_customer_context=True
    )
    assert detail["customer_context"]["explicit"] == []
    GrowthOpportunityService(db, now=NOW).evaluate_business(records["a"].id)
    db.commit()
    assert db.query(CustomerOpportunity).count() == before


def test_customer_memory_contract_ui_docs_and_migration() -> None:
    router = (ROOT / "backend/app/routers/customer_memory.py").read_text(encoding="utf-8")
    admin = (ROOT / "autonogrow-admin/admin.js").read_text(encoding="utf-8")
    model = (ROOT / "backend/app/models/customer_memory.py").read_text(encoding="utf-8")
    migration = (ROOT / "alembic/versions/20260814_17_add_customer_memory.py").read_text(
        encoding="utf-8"
    )
    for endpoint in (
        '"/customers/{customer_id}/memory"',
        '"/customers/{customer_id}/memory-summary"',
        '"/customer-memory/{memory_id}"',
        '"/customer-memory/{memory_id}/supersede"',
    ):
        assert endpoint in router
    for label in (
        "Memoria",
        "Actividad",
        "+ Añadir",
        "Servicio más frecuente",
        "Comportamiento observado",
        "Sustituir",
    ):
        assert label in admin
    assert "conversation" in model and "system" in model
    assert 'down_revision: str | Sequence[str] | None = "20260814_16"' in migration
    assert "customer_memory_items" in migration
    assert (ROOT / "docs/customer_memory_architecture.md").is_file()
    assert (ROOT / "docs/manual_test_customer_memory.md").is_file()
