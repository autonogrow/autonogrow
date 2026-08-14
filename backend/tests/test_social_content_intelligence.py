from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.core.database import Base
from app.core.security import require_business_access
from app.models import (
    Business,
    BusinessCalendarEvent,
    BusinessGalleryImage,
    BusinessGrowthSignal,
    BusinessReview,
    BusinessService,
    BusinessUser,
    Customer,
    CustomerMemoryItem,
    SocialContentProposal,
    User,
)
from app.routers.social_content import (
    accept_social_content_proposal,
    dismiss_social_content_proposal,
    get_social_content_proposal,
    list_social_content_proposals,
    social_content_proposals_summary,
)
from app.services.social_content_intelligence_service import (
    SocialContentIntelligenceService,
    serialize_social_content_proposal,
)

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def records(db: Session) -> dict[str, object]:
    business = Business(slug="social-a", name="Social A", status="active", timezone="UTC")
    other = Business(slug="social-b", name="Social B", status="active", timezone="UTC")
    admin = User(email="social-admin@test.local")
    staff = User(email="social-staff@test.local")
    outsider = User(email="social-outsider@test.local")
    db.add_all((business, other, admin, staff, outsider))
    db.flush()
    db.add_all(
        (
            BusinessUser(
                business_id=business.id,
                user_id=admin.id,
                role="business_admin",
                active=True,
            ),
            BusinessUser(
                business_id=business.id,
                user_id=staff.id,
                role="business_staff",
                active=True,
            ),
            BusinessUser(
                business_id=other.id,
                user_id=outsider.id,
                role="business_admin",
                active=True,
            ),
        )
    )
    service = BusinessService(
        business_id=business.id,
        name="Manicura",
        duration_minutes=45,
        active=True,
        bookable=True,
        position=1,
    )
    other_service = BusinessService(
        business_id=other.id,
        name="Taller",
        duration_minutes=60,
        active=True,
        bookable=True,
    )
    db.add_all((service, other_service))
    db.commit()
    return {
        "business": business,
        "other": other,
        "admin": admin,
        "staff": staff,
        "outsider": outsider,
        "service": service,
        "other_service": other_service,
    }


def signal(
    db: Session,
    business: Business,
    signal_type: str,
    *,
    service: BusinessService | None = None,
    severity: str = "medium",
    observed: dict | None = None,
    baseline: dict | None = None,
    event: BusinessCalendarEvent | None = None,
    suffix: str = "one",
) -> BusinessGrowthSignal:
    row = BusinessGrowthSignal(
        business_id=business.id,
        type=signal_type,
        status="active",
        severity=severity,
        scope_type="service" if service else "business",
        service_id=service.id if service else None,
        calendar_event_id=event.id if event else None,
        detected_at=NOW,
        period_start=NOW,
        period_end=NOW + timedelta(days=7),
        expires_at=NOW + timedelta(days=14),
        last_evaluated_at=NOW,
        reason_code=f"test_{signal_type}",
        explanation_json="{}",
        observed_json=json.dumps(observed or {"schema_version": 1}),
        baseline_json=json.dumps(baseline or {"schema_version": 1}),
        recommendation_code="test",
        dedupe_key=f"{signal_type}:{service.id if service else 'business'}:{suffix}",
    )
    db.add(row)
    db.commit()
    return row


def request(path: str = "/api/admin/businesses/social-a/social-content-proposals") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": ("testclient", 50000),
        }
    )


def proposals(db: Session, business: Business) -> list[SocialContentProposal]:
    return (
        db.query(SocialContentProposal)
        .filter(SocialContentProposal.business_id == business.id)
        .order_by(SocialContentProposal.id.asc())
        .all()
    )


def test_occupancy_creates_explainable_priority_proposal_and_is_idempotent(
    db: Session, records
) -> None:
    business = records["business"]
    signal(
        db,
        business,
        "low_future_occupancy",
        severity="high",
        observed={"occupancy_rate": 0.31, "available_minutes": 1200},
        baseline={"occupancy_rate": 0.59, "drop_points": 0.28},
    )
    first = SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    second = SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    db.commit()

    assert first.created == 1
    assert second.created == 0
    assert len(proposals(db, business)) == 1
    row = proposals(db, business)[0]
    assert (row.proposal_type, row.objective, row.priority) == (
        "availability_push",
        "fill_capacity",
        "high",
    )
    assert row.target_window_end == NOW + timedelta(days=7)
    assert "occupancy_rate" in row.evidence_json
    assert row.recommended_cta == "book_now"


def test_resolved_signal_resolves_active_proposal_and_expiry_is_distinct(
    db: Session, records
) -> None:
    business = records["business"]
    source = signal(db, business, "low_future_occupancy")
    SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    source.status = "resolved"
    source.resolved_at = NOW + timedelta(days=1)
    SocialContentIntelligenceService(db, now=NOW + timedelta(days=1)).evaluate_business(business.id)
    db.commit()
    assert proposals(db, business)[0].status == "resolved"

    old = SocialContentProposal(
        business_id=business.id,
        status="active",
        objective="educate",
        proposal_type="evergreen_content",
        priority="low",
        priority_score=10,
        reason_code="old",
        reason_text="Old",
        evidence_json="{}",
        recommended_formats_json='["carousel"]',
        recommended_cta="learn_more",
        angle_code="faq",
        available_asset_count=0,
        asset_requirement="new_photo",
        target_window_start=NOW - timedelta(days=2),
        target_window_end=NOW - timedelta(days=1),
        detected_at=NOW - timedelta(days=2),
        expires_at=NOW - timedelta(days=1),
        dedupe_key="expired:test",
        created_at=NOW - timedelta(days=2),
        updated_at=NOW - timedelta(days=2),
    )
    db.add(old)
    db.commit()
    SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    assert old.status == "expired"


def test_due_pool_global_and_service_combine_with_occupancy_without_pii(
    db: Session, records
) -> None:
    business = records["business"]
    service = records["service"]
    signal(db, business, "low_future_occupancy", observed={"occupancy_rate": 0.34})
    signal(
        db,
        business,
        "high_due_customer_pool",
        observed={"customers_due": 11, "window_days": 7},
        suffix="global",
    )
    signal(
        db,
        business,
        "high_due_customer_pool",
        service=service,
        observed={"customers_due": 11, "window_days": 7},
        baseline={"minimum_customers": 4},
        suffix="service",
    )
    SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    rows = proposals(db, business)
    assert len(rows) == 1
    row = rows[0]
    assert row.service_id == service.id
    assert row.priority_score == 100
    assert len(row.signal_links) == 2
    serialized = json.dumps(serialize_social_content_proposal(row), ensure_ascii=False)
    for forbidden in ("customer_id", "customer_name", "phone", "email", "Laura"):
        assert forbidden not in serialized


def test_due_pool_below_privacy_threshold_is_not_used(db: Session, records) -> None:
    business = records["business"]
    signal(
        db,
        business,
        "high_due_customer_pool",
        service=records["service"],
        observed={"customers_due": 3},
    )
    SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    assert proposals(db, business)[0].proposal_type == "evergreen_content"


def test_service_demand_requires_active_same_tenant_service(db: Session, records) -> None:
    business = records["business"]
    service = records["service"]
    source = signal(
        db,
        business,
        "service_demand_drop",
        service=service,
        observed={"booking_count": 2, "capacity_ratio": 1.0},
        baseline={"average_booking_count": 8, "relative_ratio": 0.25},
    )
    SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    assert proposals(db, business)[0].proposal_type == "service_push"
    service.active = False
    SocialContentIntelligenceService(db, now=NOW + timedelta(hours=1)).evaluate_business(
        business.id
    )
    db.commit()
    assert proposals(db, business)[0].status == "resolved"
    assert source.business_id == business.id


@pytest.mark.parametrize("linked", [True, False])
def test_upcoming_seasonal_event_supports_linked_and_general_scope(
    db: Session, records, linked: bool
) -> None:
    business = records["business"]
    service = records["service"] if linked else None
    event = BusinessCalendarEvent(
        business_id=business.id,
        title="Navidad",
        starts_at=NOW + timedelta(days=10),
        ends_at=NOW + timedelta(days=20),
        service_id=service.id if service else None,
        enabled=True,
        yearly_recurrence=True,
    )
    db.add(event)
    db.commit()
    signal(
        db,
        business,
        "seasonal_window",
        service=service,
        event=event,
        observed={"days_until_start": 10, "event_title": "Navidad"},
    )
    SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    row = proposals(db, business)[0]
    assert row.proposal_type == "seasonal_content"
    assert row.source_event_id == event.id
    assert row.service_id == (service.id if service else None)
    assert row.priority == "high"


def test_review_rules_require_recent_text_positive_approval_and_tenant_isolation(
    db: Session, records
) -> None:
    business = records["business"]
    other = records["other"]
    valid = BusinessReview(
        business_id=business.id,
        service_id=records["service"].id,
        source="google",
        external_id="valid",
        rating=5,
        review_text="Excelente atención de Ana Cliente",
        status="usable",
        social_use_approved=True,
        reviewed_at=NOW - timedelta(days=2),
    )
    db.add_all(
        (
            valid,
            BusinessReview(
                business_id=business.id,
                source="google",
                external_id="old",
                rating=5,
                review_text="Antigua",
                status="usable",
                social_use_approved=True,
                reviewed_at=NOW - timedelta(days=100),
            ),
            BusinessReview(
                business_id=business.id,
                source="google",
                external_id="empty",
                rating=5,
                review_text="",
                status="usable",
                social_use_approved=True,
                reviewed_at=NOW,
            ),
            BusinessReview(
                business_id=other.id,
                source="google",
                external_id="other",
                rating=5,
                review_text="Other Private Name",
                status="usable",
                social_use_approved=True,
                reviewed_at=NOW,
            ),
        )
    )
    db.commit()
    SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    rows = proposals(db, business)
    assert len(rows) == 1
    payload = serialize_social_content_proposal(rows[0])
    assert payload["type"] == "review_social_proof"
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "Ana Cliente" not in encoded
    assert "Other Private Name" not in encoded
    assert valid.id == payload["source_review_id"]


def test_evergreen_is_finite_and_reports_business_asset_availability(
    db: Session, records
) -> None:
    business = records["business"]
    db.add(
        BusinessGalleryImage(
            business_id=business.id,
            url="/uploads/businesses/social-a/example.jpg",
            active=True,
        )
    )
    db.commit()
    SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    rows = proposals(db, business)
    assert len(rows) == 1
    payload = serialize_social_content_proposal(rows[0])
    assert payload["type"] == "evergreen_content"
    assert payload["available_assets"] == {"available": True, "count": 1, "scope": "business"}
    assert payload["asset_requirement"] == "existing_media"


def test_accept_and_dismiss_lifecycle_keep_aggregate_snapshot(db: Session, records) -> None:
    business = records["business"]
    admin = records["admin"]
    signal(db, business, "low_future_occupancy", observed={"occupancy_rate": 0.31})
    SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    first = proposals(db, business)[0]
    accepted = accept_social_content_proposal(
        business.slug, first.id, request(), actor=admin, db=db
    )
    assert accepted["proposal"]["status"] == "accepted"
    snapshot = json.dumps(accepted["proposal"]["accepted_context"], ensure_ascii=False)
    assert "occupancy_rate" in snapshot
    for forbidden in ("customer_name", "phone", "email", "conversation", "sensitive"):
        assert forbidden not in snapshot
    repeat = accept_social_content_proposal(
        business.slug, first.id, request(), actor=admin, db=db
    )
    assert repeat["idempotent"] is True

    second_signal = signal(
        db, business, "service_demand_drop", service=records["service"], suffix="dismiss"
    )
    SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    second = next(row for row in proposals(db, business) if row.status == "active")
    dismissed = dismiss_social_content_proposal(
        business.slug, second.id, request(), actor=admin, db=db
    )
    assert dismissed["proposal"]["status"] == "dismissed"
    assert second_signal.status == "active"


def test_api_filters_summary_tenant_isolation_and_permissions(db: Session, records) -> None:
    business = records["business"]
    signal(db, business, "low_future_occupancy", severity="high")
    SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    response = list_social_content_proposals(
        business.slug,
        status="active",
        objective="fill_capacity",
        type="availability_push",
        service_id=None,
        priority="high",
        limit=100,
        db=db,
    )
    assert len(response["proposals"]) == 1
    summary = social_content_proposals_summary(business.slug, db)
    assert summary["active_count"] == summary["high_priority_count"] == 1
    assert summary["by_format"]["story"] == 1
    detail = get_social_content_proposal(business.slug, response["proposals"][0]["id"], db)
    assert detail["proposal"]["business_id"] == business.id
    with pytest.raises(HTTPException) as missing:
        get_social_content_proposal(records["other"].slug, response["proposals"][0]["id"], db)
    assert missing.value.status_code == 404

    assert require_business_access(business.slug, records["staff"], db) == records["staff"]
    with pytest.raises(HTTPException) as forbidden:
        require_business_access(business.slug, records["outsider"], db)
    assert forbidden.value.status_code == 403


def test_customer_memory_and_conversations_are_never_read_or_serialized(
    db: Session, records
) -> None:
    business = records["business"]
    customer = Customer(
        business_id=business.id,
        name="Laura Privada",
        phone="+34111222333",
        email="laura-private@example.com",
    )
    db.add(customer)
    db.flush()
    db.add(
        CustomerMemoryItem(
            business_id=business.id,
            customer_id=customer.id,
            category="preference",
            key="private_color",
            value="Secreto sensible",
            value_type="text",
            source_type="manual",
            status="active",
            is_sensitive=True,
        )
    )
    db.commit()
    SocialContentIntelligenceService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    payload = json.dumps(
        [serialize_social_content_proposal(row) for row in proposals(db, business)],
        ensure_ascii=False,
    )
    for forbidden in (
        "Laura Privada",
        "+34111222333",
        "laura-private@example.com",
        "Secreto sensible",
        "private_color",
    ):
        assert forbidden not in payload


def test_admin_rrss_area_renders_recommended_ideas_and_actions() -> None:
    html = (ROOT / "autonogrow-admin" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "autonogrow-admin" / "admin.js").read_text(encoding="utf-8")
    assert 'data-admin-section="instagram-content"' in html
    assert 'id="social-content-ideas-title">Ideas recomendadas' in html
    assert "loadSocialContentProposals" in js
    assert "social-content-proposals" in js
    assert '>Usar idea</button>' in js
    assert '>Descartar</button>' in js
    assert "Usar una idea todavía no crea ni publica contenido" in html


def test_existing_maintenance_pipeline_registers_social_content_task() -> None:
    maintenance = (ROOT / "scripts" / "run_maintenance.py").read_text(encoding="utf-8")
    assert '"social-content-intelligence"' in maintenance
    assert "SocialContentIntelligenceService(db).evaluate_business" in maintenance
