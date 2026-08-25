from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models import (
    AuditLog,
    Business,
    BusinessGrowthSignal,
    BusinessService,
    BusinessUser,
    InstagramContentSettings,
    SocialContentProposal,
    SocialContentProposalSignal,
    SocialIdeaReview,
    SocialPromotionRevision,
    User,
)
from app.routers.social_content import router as business_social_router
from app.routers.social_content_workflow import router as owner_social_router
from app.services.instagram_content_service import ensure_promotion_window

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def workflow_context():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = session_factory()
    business = Business(slug="workflow-a", name="Estudio A", status="active", timezone="UTC")
    other = Business(slug="workflow-b", name="Estudio B", status="active", timezone="UTC")
    business_owner = User(email="business-owner-a@test.local")
    other_owner = User(email="business-owner-b@test.local")
    staff = User(email="business-staff-a@test.local")
    autonogrow_admin = User(email="autonogrow-admin@test.local", is_owner=True)
    db.add_all((business, other, business_owner, other_owner, staff, autonogrow_admin))
    db.flush()
    db.add_all(
        (
            BusinessUser(
                business_id=business.id,
                user_id=business_owner.id,
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
                user_id=other_owner.id,
                role="business_admin",
                active=True,
            ),
        )
    )
    service = BusinessService(
        business_id=business.id,
        name="Manicura",
        active=True,
        bookable=True,
        price_amount=Decimal("40.00"),
        currency="EUR",
    )
    db.add(service)
    db.flush()
    signals = []
    for index, signal_type in enumerate(("service_demand_drop", "low_future_occupancy"), 1):
        signal = BusinessGrowthSignal(
            business_id=business.id,
            type=signal_type,
            status="active",
            severity="high",
            scope_type="service" if signal_type == "service_demand_drop" else "business",
            service_id=service.id if signal_type == "service_demand_drop" else None,
            detected_at=NOW,
            period_start=NOW,
            period_end=NOW + timedelta(days=7),
            expires_at=NOW + timedelta(days=14),
            last_evaluated_at=NOW,
            reason_code=f"workflow_{signal_type}",
            explanation_json="{}",
            observed_json='{"occupancy_rate":0.30}',
            baseline_json='{"occupancy_rate":0.60}',
            recommendation_code="social_visibility",
            dedupe_key=f"workflow:{index}",
        )
        db.add(signal)
        signals.append(signal)
    db.flush()
    proposal = SocialContentProposal(
        business_id=business.id,
        status="active",
        objective="promote_service",
        proposal_type="service_push",
        priority="high",
        priority_score=82,
        service_id=service.id,
        reason_code="combined_low_occupancy_and_demand",
        reason_text="La demanda y la ocupacion han bajado.",
        evidence_json='{"schema_version":1,"occupancy_rate":0.30}',
        recommended_formats_json='["story","static_post"]',
        recommended_cta="book_now",
        angle_code="availability",
        available_asset_count=0,
        asset_requirement="none",
        target_window_start=NOW,
        target_window_end=NOW + timedelta(days=7),
        detected_at=NOW,
        expires_at=NOW + timedelta(days=14),
        dedupe_key="workflow:proposal:a",
    )
    legacy = SocialContentProposal(
        business_id=business.id,
        status="accepted",
        objective="educate",
        proposal_type="evergreen_content",
        priority="low",
        priority_score=20,
        reason_code="legacy",
        reason_text="Aceptacion historica.",
        evidence_json="{}",
        recommended_formats_json='["static_post"]',
        recommended_cta="learn_more",
        angle_code="faq",
        available_asset_count=9,
        asset_requirement="existing_media",
        target_window_start=NOW,
        target_window_end=NOW + timedelta(days=7),
        detected_at=NOW - timedelta(days=20),
        expires_at=NOW + timedelta(days=14),
        accepted_at=NOW - timedelta(days=10),
        accepted_by_user_id=autonogrow_admin.id,
        accepted_context_json='{"legacy":true}',
        dedupe_key="workflow:legacy:a",
    )
    db.add_all((proposal, legacy, InstagramContentSettings(business_id=business.id, enabled=True)))
    db.flush()
    for signal in signals:
        db.add(SocialContentProposalSignal(proposal_id=proposal.id, signal_id=signal.id))
    db.commit()

    actor = {"user": business_owner}
    app = FastAPI()
    app.include_router(business_social_router)
    app.include_router(owner_social_router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: actor["user"]
    client = TestClient(app)
    yield {
        "db": db,
        "client": client,
        "actor": actor,
        "business": business,
        "other": other,
        "business_owner": business_owner,
        "other_owner": other_owner,
        "staff": staff,
        "autonogrow_admin": autonogrow_admin,
        "service": service,
        "proposal": proposal,
        "legacy": legacy,
    }
    client.close()
    db.close()
    engine.dispose()


def business_api(ctx, slug: str | None = None) -> str:
    return f"/api/admin/businesses/{slug or ctx['business'].slug}"


def owner_api(ctx, business_id: int | None = None) -> str:
    return f"/api/owner/businesses/{business_id or ctx['business'].id}/social-content"


def set_actor(ctx, user: User) -> None:
    ctx["actor"]["user"] = user


def test_real_roles_enforce_owner_first_tenant_and_admin_boundaries(workflow_context):
    ctx = workflow_context
    listing = ctx["client"].get(f"{business_api(ctx)}/social-content-proposals?status=active")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["proposals"]] == [ctx["proposal"].id]
    assert "available_assets" not in listing.json()["proposals"][0]
    seen_url = f"{business_api(ctx)}/social-content-proposals/{ctx['proposal'].id}/seen"
    assert ctx["client"].post(seen_url).json()["idempotent"] is False
    assert ctx["client"].post(seen_url).json()["idempotent"] is True
    assert (
        ctx["db"].query(AuditLog).filter_by(action="social_idea_business_owner_seen").count()
        == 1
    )

    set_actor(ctx, ctx["staff"])
    assert (
        ctx["client"].get(f"{business_api(ctx)}/social-content-proposals").status_code == 403
    )
    set_actor(ctx, ctx["other_owner"])
    assert (
        ctx["client"].get(f"{business_api(ctx)}/social-content-proposals").status_code == 403
    )
    own_other = ctx["client"].get(
        f"{business_api(ctx, ctx['other'].slug)}/social-content-proposals"
    )
    assert own_other.status_code == 200
    assert own_other.json()["proposals"] == []

    set_actor(ctx, ctx["autonogrow_admin"])
    assert (
        ctx["client"].get(f"{business_api(ctx)}/social-content-proposals").status_code == 403
    )
    reviews = ctx["client"].get(f"{owner_api(ctx)}/idea-reviews")
    assert reviews.status_code == 200
    assert reviews.json()["reviews"] == []


def test_legacy_accepted_is_not_owner_interest_or_admin_task(workflow_context):
    ctx = workflow_context
    listing = ctx["client"].get(f"{business_api(ctx)}/social-content-proposals?status=accepted")
    assert listing.status_code == 200
    legacy = listing.json()["proposals"][0]
    assert legacy["legacy_accepted"] is True
    assert legacy["owner_first"] is False
    assert legacy["owner_state"] == "legacy_accepted"
    response = ctx["client"].post(
        f"{business_api(ctx)}/social-content-proposals/{ctx['legacy'].id}/accept",
        json={"intent": "visibility"},
    )
    assert response.status_code == 409
    assert ctx["db"].query(SocialIdeaReview).count() == 0


def test_owner_interest_creates_one_admin_review_and_approved_promotion_generation(
    workflow_context,
):
    ctx = workflow_context
    proposal_url = f"{business_api(ctx)}/social-content-proposals/{ctx['proposal'].id}"
    accepted = ctx["client"].post(f"{proposal_url}/accept", json={"intent": "promotion"})
    assert accepted.status_code == 200, accepted.text
    repeated = ctx["client"].post(f"{proposal_url}/accept", json={"intent": "promotion"})
    assert repeated.status_code == 200
    assert repeated.json()["idempotent"] is True
    assert ctx["db"].query(SocialIdeaReview).count() == 1
    review = ctx["db"].query(SocialIdeaReview).one()
    assert review.status == "pending"
    assert review.owner_accepted_by_user_id == ctx["business_owner"].id

    set_actor(ctx, ctx["autonogrow_admin"])
    queue = ctx["client"].get(f"{owner_api(ctx)}/idea-reviews")
    assert queue.status_code == 200
    payload = queue.json()["reviews"][0]
    assert payload["production_readiness"]["status"] == "needs_material"
    proposed = ctx["client"].post(
        f"{owner_api(ctx)}/idea-reviews/{review.id}/promotion",
        json={
            "discount_type": "percent",
            "discount_value": "25.00",
            "regular_price": "40.00",
            "promotional_price": "30.00",
            "currency": "EUR",
            "valid_from": "2026-09-01T00:00:00Z",
            "valid_until": "2026-09-08T00:00:00Z",
            "days": [0, 1, 2, 3, 4],
            "scope": "Servicio de manicura",
        },
    )
    assert proposed.status_code == 201, proposed.text
    revision_id = proposed.json()["promotion"]["revisions"][0]["id"]
    assert ctx["service"].price_amount == Decimal("40.00")

    set_actor(ctx, ctx["business_owner"])
    decision = ctx["client"].post(
        f"{proposal_url}/promotion/decision",
        json={"revision_id": revision_id, "decision": "approve"},
    )
    assert decision.status_code == 200, decision.text
    revision = ctx["db"].get(SocialPromotionRevision, revision_id)
    assert revision.status == "owner_approved"
    assert revision.owner_decided_by_user_id == ctx["business_owner"].id

    set_actor(ctx, ctx["autonogrow_admin"])
    generated = ctx["client"].post(
        f"{owner_api(ctx)}/idea-reviews/{review.id}/decision",
        json={"decision": "approve", "format": "story"},
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["generated"] is True
    package = generated.json()["content"]["current_version"]["editorial_package"]
    assert package["generation_context"]["generator_version"] == "deterministic_v1"
    assert package["promotion"]["status"] == "owner_approved"
    assert "rentab" not in json.dumps(package, ensure_ascii=False).lower()
    assert ctx["service"].price_amount == Decimal("40.00")
    content = ctx["proposal"].generated_content
    ensure_promotion_window(ctx["db"], content, datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc))
    with pytest.raises(HTTPException) as exc:
        ensure_promotion_window(
            ctx["db"], content, datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
        )
    assert exc.value.status_code == 409
    actions = {row.action for row in ctx["db"].query(AuditLog).all()}
    assert {
        "social_idea_business_owner_accepted",
        "social_promotion_business_owner_requested",
        "social_promotion_autonogrow_admin_proposed",
        "social_promotion_business_owner_approved",
        "social_idea_autonogrow_admin_approved",
        "social_content_draft_generated",
    } <= actions


def test_promotion_revision_and_business_idor_are_enforced(workflow_context):
    ctx = workflow_context
    proposal_url = f"{business_api(ctx)}/social-content-proposals/{ctx['proposal'].id}"
    assert (
        ctx["client"].post(f"{proposal_url}/accept", json={"intent": "promotion"}).status_code
        == 200
    )
    review = ctx["db"].query(SocialIdeaReview).one()
    set_actor(ctx, ctx["autonogrow_admin"])
    assert (
        ctx["client"].get(f"{owner_api(ctx, ctx['other'].id)}/idea-reviews").status_code
        == 200
    )
    assert ctx["client"].get(f"{owner_api(ctx, ctx['other'].id)}/idea-reviews").json()[
        "reviews"
    ] == []
    invalid_price = ctx["client"].post(
        f"{owner_api(ctx)}/idea-reviews/{review.id}/promotion",
        json={
            "discount_type": "fixed",
            "discount_value": "5.00",
            "regular_price": "41.00",
            "promotional_price": "36.00",
            "currency": "EUR",
            "valid_from": "2026-09-01T00:00:00Z",
            "valid_until": "2026-09-08T00:00:00Z",
            "days": [],
            "scope": "Manicura",
        },
    )
    assert invalid_price.status_code == 409
