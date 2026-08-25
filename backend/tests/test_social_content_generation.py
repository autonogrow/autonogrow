from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user, require_owner
from app.models import (
    Business,
    BusinessGrowthSignal,
    BusinessReview,
    BusinessService,
    BusinessUser,
    InstagramContentSettings,
    InstagramRawAsset,
    SocialContentProposal,
    SocialContentProposalSignal,
    SocialIdeaReview,
    User,
)
from app.routers.social_content_generation import _proposal_or_404
from app.routers.social_content_generation import router as social_content_generation_router
from app.schemas.social_content_generation import EditorialPackageEdit
from app.services.social_content_generation_service import (
    GENERATOR_VERSION,
    generate_from_proposal,
    regenerate_content,
    serialize_editorial_package,
    update_generated_draft,
)

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def records(db: Session) -> dict[str, object]:
    business = Business(
        slug="generation-a",
        name="Estudio Luz",
        category="Belleza",
        city="Valencia",
        status="active",
        timezone="UTC",
    )
    other = Business(slug="generation-b", name="Otro", status="active", timezone="UTC")
    actor = User(email="generation-admin@test.local")
    staff = User(email="generation-staff@test.local")
    owner = User(email="generation-owner@test.local", is_owner=True)
    db.add_all((business, other, actor, staff, owner))
    db.flush()
    db.add_all(
        (
            BusinessUser(
                business_id=business.id,
                user_id=actor.id,
                role="business_admin",
                active=True,
            ),
            BusinessUser(
                business_id=business.id,
                user_id=staff.id,
                role="business_staff",
                active=True,
            ),
        )
    )
    service = BusinessService(
        business_id=business.id,
        name="Manicura",
        category="Uñas",
        active=True,
        bookable=True,
    )
    db.add(service)
    db.flush()
    db.add(InstagramContentSettings(business_id=business.id, enabled=True))
    snapshot = {
        "schema_version": 1,
        "proposal_id": 1,
        "objective": "promote_service",
        "type": "service_push",
        "service": {"id": service.id, "name": service.name},
        "reason_code": "test",
        "reason_text": "Contexto agregado",
        "evidence": {"schema_version": 1},
        "recommended_formats": ["reel", "story", "carousel", "static_post"],
        "recommended_cta": "book_now",
        "angle_code": "process",
        "available_asset_count": 0,
        "asset_requirement": "new_video",
        "target_window_start": NOW.isoformat(),
        "target_window_end": (NOW + timedelta(days=7)).isoformat(),
    }
    proposal = SocialContentProposal(
        business_id=business.id,
        status="accepted",
        objective="promote_service",
        proposal_type="service_push",
        priority="normal",
        priority_score=50,
        service_id=service.id,
        reason_code="test",
        reason_text="Contexto agregado",
        evidence_json='{"schema_version":1}',
        recommended_formats_json='["reel","story","carousel","static_post"]',
        recommended_cta="book_now",
        angle_code="process",
        available_asset_count=0,
        asset_requirement="new_video",
        target_window_start=NOW,
        target_window_end=NOW + timedelta(days=7),
        detected_at=NOW,
        expires_at=NOW + timedelta(days=14),
        accepted_at=NOW,
        accepted_by_user_id=actor.id,
        accepted_context_json=json.dumps(snapshot),
        dedupe_key="generation:test",
    )
    db.add(proposal)
    db.flush()
    db.add(
        SocialIdeaReview(
            proposal=proposal,
            business_id=business.id,
            status="approved",
            owner_intent="visibility",
            owner_accepted_by_user_id=actor.id,
            owner_accepted_at=NOW,
            owner_context_json=json.dumps(snapshot),
            presentation_json='{"template_version":"test_v1"}',
            template_version="test_v1",
            admin_reviewed_by_user_id=owner.id,
            admin_reviewed_at=NOW,
        )
    )
    db.commit()
    return {
        "business": business,
        "other": other,
        "actor": actor,
        "staff": staff,
        "owner": owner,
        "service": service,
        "proposal": proposal,
    }


@pytest.mark.parametrize(
    ("editorial_format", "field"),
    (
        ("reel", "shot_list"),
        ("story", "story_frames"),
        ("carousel", "slides"),
        ("static_post", "on_screen_text"),
    ),
)
def test_generates_safe_structured_draft_for_each_format(
    db: Session, records, editorial_format: str, field: str
) -> None:
    proposal = records["proposal"]
    content, version, idempotent = generate_from_proposal(
        db,
        proposal=proposal,
        actor=records["actor"],
        requested_format=editorial_format,
        now=NOW,
    )
    db.commit()
    package = serialize_editorial_package(version)

    assert not idempotent
    assert content.status == "draft"
    assert content.source_proposal_id == proposal.id
    assert package is not None
    assert package["editorial_format"] == editorial_format
    assert package[field]
    assert package["generation_context"]["generator_version"] == GENERATOR_VERSION
    assert package["asset_plan"]["media_generation_requested"] is False
    assert 3 <= len(package["hashtags"]) <= 8
    combined = json.dumps(package, ensure_ascii=False).lower()
    assert "descuento" not in combined
    assert "garantizado" not in combined


def test_generation_is_idempotent_and_hook_rotation_is_deterministic(db: Session, records) -> None:
    first_content, first_version, first_idempotent = generate_from_proposal(
        db, proposal=records["proposal"], actor=records["actor"], now=NOW
    )
    db.commit()
    second_content, second_version, second_idempotent = generate_from_proposal(
        db, proposal=records["proposal"], actor=records["actor"], now=NOW
    )

    assert not first_idempotent
    assert second_idempotent
    assert second_content.id == first_content.id
    assert second_version.id == first_version.id


def test_legacy_accepted_proposal_cannot_generate_without_explicit_admin_review(
    db: Session, records
) -> None:
    proposal = records["proposal"]
    db.delete(proposal.idea_review)
    db.commit()
    db.refresh(proposal)

    with pytest.raises(HTTPException) as exc:
        generate_from_proposal(db, proposal=proposal, actor=records["owner"], now=NOW)

    assert exc.value.status_code == 409
    assert "Explicit AutonoGrow Admin" in str(exc.value.detail)


def test_assets_are_tenant_scoped_active_and_service_ranked(db: Session, records) -> None:
    db.add_all(
        (
            InstagramRawAsset(
                business_id=records["business"].id,
                service_id=records["service"].id,
                active=True,
                original_filename="service.mp4",
                storage_key="a/service.mp4",
                media_type="video/mp4",
                size_bytes=10,
                created_at=NOW - timedelta(days=4),
            ),
            InstagramRawAsset(
                business_id=records["business"].id,
                active=True,
                original_filename="recent.mp4",
                storage_key="a/recent.mp4",
                media_type="video/mp4",
                size_bytes=10,
                created_at=NOW,
            ),
            InstagramRawAsset(
                business_id=records["business"].id,
                active=False,
                original_filename="inactive.mp4",
                storage_key="a/inactive.mp4",
                media_type="video/mp4",
                size_bytes=10,
            ),
            InstagramRawAsset(
                business_id=records["other"].id,
                active=True,
                original_filename="foreign.mp4",
                storage_key="b/foreign.mp4",
                media_type="video/mp4",
                size_bytes=10,
            ),
        )
    )
    db.commit()
    _, version, _ = generate_from_proposal(
        db, proposal=records["proposal"], actor=records["actor"], now=NOW
    )
    package = serialize_editorial_package(version)
    recommendations = package["asset_plan"]["recommended"]

    assert [item["id"] for item in recommendations] == [1, 2]
    assert package["asset_plan"]["missing"] == []


def test_changed_signal_warns_without_refreshing_snapshot(db: Session, records) -> None:
    signal = BusinessGrowthSignal(
        business_id=records["business"].id,
        type="service_demand_drop",
        status="resolved",
        severity="medium",
        scope_type="service",
        service_id=records["service"].id,
        detected_at=NOW,
        period_start=NOW,
        period_end=NOW + timedelta(days=7),
        expires_at=NOW + timedelta(days=14),
        last_evaluated_at=NOW,
        reason_code="test",
        explanation_json="{}",
        observed_json="{}",
        baseline_json="{}",
        recommendation_code="test",
        dedupe_key="signal:generation",
    )
    db.add(signal)
    db.flush()
    db.add(SocialContentProposalSignal(proposal_id=records["proposal"].id, signal_id=signal.id))
    db.commit()

    _, version, _ = generate_from_proposal(
        db, proposal=records["proposal"], actor=records["actor"], now=NOW
    )
    package = serialize_editorial_package(version)
    assert package["generation_context"]["warnings"] == [f"source_signal_{signal.id}_changed"]
    assert package["headline"].startswith("Manicura")


@pytest.mark.parametrize("status", ("active", "resolved", "expired", "dismissed"))
def test_non_accepted_proposal_is_blocked(db: Session, records, status: str) -> None:
    records["proposal"].status = status
    db.commit()
    with pytest.raises(HTTPException) as error:
        generate_from_proposal(db, proposal=records["proposal"], actor=records["actor"], now=NOW)
    assert error.value.status_code == 409


def test_expired_accepted_proposal_is_blocked(db: Session, records) -> None:
    records["proposal"].expires_at = NOW
    db.commit()
    with pytest.raises(HTTPException, match="expired"):
        generate_from_proposal(db, proposal=records["proposal"], actor=records["actor"], now=NOW)


def test_regeneration_and_manual_edit_preserve_history(db: Session, records) -> None:
    content, first, _ = generate_from_proposal(
        db, proposal=records["proposal"], actor=records["actor"], now=NOW
    )
    db.commit()
    second = regenerate_content(
        db,
        content=content,
        actor=records["actor"],
        requested_format="carousel",
        now=NOW,
    )
    package = serialize_editorial_package(second)
    edit = EditorialPackageEdit(
        hook="Hook revisado",
        headline=package["headline"],
        caption="Caption revisado",
        cta_text=package["cta"]["text"],
        on_screen_text=package["on_screen_text"],
        visual_direction=package["visual_direction"],
        shot_list=package["shot_list"],
        slides=package["slides"],
        story_frames=package["story_frames"],
        hashtags=package["hashtags"],
    )
    third, changed = update_generated_draft(db, content=content, actor=records["actor"], edit=edit)
    db.commit()

    assert (first.version_number, second.version_number, third.version_number) == (1, 2, 3)
    assert serialize_editorial_package(first)["hook"] != serialize_editorial_package(second)["hook"]
    assert changed
    assert third.generation_source == "manual_edit"
    assert serialize_editorial_package(first)["hook"] != "Hook revisado"
    assert serialize_editorial_package(third)["hook"] == "Hook revisado"
    assert content.status == "draft"


def test_approved_review_never_copies_text_or_personal_data(db: Session, records) -> None:
    review = BusinessReview(
        business_id=records["business"].id,
        service_id=records["service"].id,
        source="test",
        external_id="review-private",
        rating=5,
        review_text="Soy María Pérez, mi teléfono es 600123123 y este es mi texto privado",
        status="usable",
        social_use_approved=True,
        reviewed_at=NOW,
    )
    db.add(review)
    db.flush()
    records["proposal"].source_review_id = review.id
    db.commit()

    _, version, _ = generate_from_proposal(
        db, proposal=records["proposal"], actor=records["actor"], now=NOW
    )
    serialized = json.dumps(serialize_editorial_package(version), ensure_ascii=False).lower()
    assert "maría" not in serialized
    assert "600123123" not in serialized
    assert "texto privado" not in serialized


def test_generation_permissions_and_proposal_tenant_isolation(db: Session, records) -> None:
    assert require_owner(records["owner"]) == records["owner"]
    for role in ("actor", "staff"):
        with pytest.raises(HTTPException) as forbidden:
            require_owner(records[role])
        assert forbidden.value.status_code == 403
    with pytest.raises(HTTPException) as hidden:
        _proposal_or_404(
            db,
            business_id=records["other"].id,
            proposal_id=records["proposal"].id,
        )
    assert hidden.value.status_code == 404


def test_generation_api_is_owner_only_and_tenant_scoped(db: Session, records) -> None:
    app = FastAPI()
    app.include_router(social_content_generation_router)
    current_actor = {"user": records["owner"]}

    def override_db():
        yield db

    def override_user():
        return current_actor["user"]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    with TestClient(app) as client:
        proposal_id = records["proposal"].id
        generated = client.post(
            f"/api/admin/businesses/{records['business'].slug}/social-content-proposals/"
            f"{proposal_id}/generate",
            json={},
        )
        assert generated.status_code == 201

        for role in ("actor", "staff"):
            current_actor["user"] = records[role]
            assert (
                client.post(
                    f"/api/admin/businesses/{records['business'].slug}/social-content-proposals/"
                    f"{proposal_id}/generate",
                    json={},
                ).status_code
                == 403
            )

        current_actor["user"] = records["owner"]
        assert (
            client.post(
                f"/api/admin/businesses/{records['other'].slug}/social-content-proposals/"
                f"{proposal_id}/generate",
                json={},
            ).status_code
            == 404
        )


def test_business_owner_ui_exposes_interest_and_final_approval_without_admin_review() -> None:
    admin = (Path(__file__).resolve().parents[2] / "autonogrow-admin" / "admin.js").read_text(
        encoding="utf-8"
    )
    for marker in (
        "Me interesa",
        "Estudiar promoción",
        "data-admin-instagram-final-approval",
        "/validate",
    ):
        assert marker in admin
    for forbidden in (
        "Generar borrador",
        "data-generated-editor",
        "data-generated-regenerate",
        "/generated-draft",
        "/regenerate",
        "/editorial-review",
    ):
        assert forbidden not in admin
