from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models import (
    AuditLog,
    Business,
    BusinessChannelControl,
    BusinessChannelIntegration,
    BusinessUser,
    InstagramContent,
    InstagramContentSettings,
    InstagramContentValidation,
    InstagramContentVersion,
    InstagramFinalAsset,
    InstagramPublishJob,
    InstagramRawAsset,
    MetaIntegrationJob,
    User,
)
from app.routers.instagram_content import admin_router, owner_router


@pytest.fixture
def editorial_context(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = session_factory()
    business = Business(slug="editorial-a", name="Editorial A", status="active")
    other_business = Business(slug="editorial-b", name="Editorial B", status="active")
    owner = User(email="owner@editorial.test", is_owner=True)
    admin = User(email="admin@editorial.test")
    staff = User(email="staff@editorial.test")
    other_admin = User(email="other-admin@editorial.test")
    customer = User(email="customer@editorial.test")
    db.add_all([business, other_business, owner, admin, staff, other_admin, customer])
    db.flush()
    db.add_all(
        [
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
                business_id=other_business.id,
                user_id=other_admin.id,
                role="business_admin",
                active=True,
            ),
        ]
    )
    db.commit()

    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(owner_router)
    actor = {"user": owner}

    def override_db() -> Iterator[Session]:
        yield db

    def override_user() -> User:
        return actor["user"]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    monkeypatch.setattr("app.routers.instagram_content.get_uploads_dir", lambda: tmp_path)
    with TestClient(app) as client:
        yield {
            "client": client,
            "db": db,
            "actor": actor,
            "business": business,
            "other_business": other_business,
            "owner": owner,
            "admin": admin,
            "staff": staff,
            "other_admin": other_admin,
            "customer": customer,
        }
    db.close()
    engine.dispose()


def owner_base(ctx) -> str:
    return f"/api/owner/businesses/{ctx['business'].id}/instagram-content"


def admin_base(ctx, slug: str | None = None) -> str:
    return f"/api/admin/businesses/{slug or ctx['business'].slug}/instagram-content"


def set_actor(ctx, user: User) -> None:
    ctx["actor"]["user"] = user


def enable_service(ctx) -> None:
    set_actor(ctx, ctx["owner"])
    response = ctx["client"].patch(f"{owner_base(ctx)}/settings", json={"enabled": True})
    assert response.status_code == 200


def enable_publish_integration(ctx) -> None:
    ctx["db"].add_all(
        [
            BusinessChannelControl(
                business_id=ctx["business"].id,
                channel="instagram",
                status="approved",
                integrated_delivery_enabled=True,
                connector_policy="owner_only",
            ),
            BusinessChannelIntegration(
                business_id=ctx["business"].id,
                channel="instagram",
                provider="instagram",
                external_account_id="editorial-publish-account",
                integration_status="connected",
                health_status="healthy",
            ),
        ]
    )
    ctx["db"].commit()


def create_content_with_asset(ctx) -> tuple[int, int, int]:
    enable_service(ctx)
    response = ctx["client"].post(
        f"{owner_base(ctx)}/contents",
        json={
            "title": "Campaña de agosto",
            "caption": "Primera propuesta",
            "format": "single_image",
            "planned_publish_at": "2026-08-20T10:00:00+02:00",
        },
    )
    assert response.status_code == 201
    content_id = response.json()["id"]
    asset = InstagramFinalAsset(
        business_id=ctx["business"].id,
        content_id=content_id,
        uploaded_by_user_id=ctx["owner"].id,
        original_filename="final.png",
        storage_key=f"_instagram_content/{ctx['business'].id}/final/final.png",
        media_type="image/png",
        size_bytes=12,
    )
    ctx["db"].add(asset)
    ctx["db"].commit()
    response = ctx["client"].put(
        f"{owner_base(ctx)}/contents/{content_id}/material",
        json={
            "caption": "Versión lista",
            "format": "single_image",
            "asset_ids": [asset.id],
            "cover_asset_id": asset.id,
        },
    )
    assert response.status_code == 200
    version_id = response.json()["current_version"]["id"]
    return content_id, asset.id, version_id


def test_owner_controls_service_and_admin_controls_validation_delegation(editorial_context):
    ctx = editorial_context
    set_actor(ctx, ctx["admin"])
    assert (
        ctx["client"].patch(f"{owner_base(ctx)}/settings", json={"enabled": True}).status_code
        == 403
    )

    set_actor(ctx, ctx["owner"])
    assert (
        ctx["client"].patch(f"{owner_base(ctx)}/settings", json={"enabled": True}).status_code
        == 200
    )
    assert (
        ctx["client"]
        .patch(
            f"{admin_base(ctx)}/settings/validation-delegation",
            json={"owner_can_validate_instagram_content": True},
        )
        .status_code
        == 403
    )

    set_actor(ctx, ctx["admin"])
    response = ctx["client"].patch(
        f"{admin_base(ctx)}/settings/validation-delegation",
        json={"owner_can_validate_instagram_content": True},
    )
    assert response.status_code == 200
    assert response.json()["owner_can_validate_instagram_content"] is True
    assert {row.action for row in ctx["db"].query(AuditLog).all()} >= {
        "instagram_content_service_updated",
        "instagram_owner_validation_delegation_updated",
    }


@pytest.mark.parametrize("role", ["staff", "customer"])
def test_staff_and_customer_have_no_access(editorial_context, role):
    ctx = editorial_context
    enable_service(ctx)
    set_actor(ctx, ctx[role])
    assert ctx["client"].get(f"{admin_base(ctx)}/contents").status_code == 403
    assert ctx["client"].get(f"{owner_base(ctx)}/contents").status_code == 403


def test_admin_is_isolated_to_own_business_and_cannot_create_final_content(editorial_context):
    ctx = editorial_context
    content_id, _asset_id, _version_id = create_content_with_asset(ctx)
    ctx["db"].add(InstagramContentSettings(business_id=ctx["other_business"].id, enabled=True))
    ctx["db"].commit()
    set_actor(ctx, ctx["other_admin"])
    assert ctx["client"].get(f"{admin_base(ctx)}/contents/{content_id}").status_code == 403
    assert (
        ctx["client"]
        .get(f"{admin_base(ctx, ctx['other_business'].slug)}/contents/{content_id}")
        .status_code
        == 404
    )

    set_actor(ctx, ctx["admin"])
    response = ctx["client"].post(
        f"{admin_base(ctx)}/contents",
        json={"title": "No permitido", "caption": "x", "format": "single_image"},
    )
    assert response.status_code in {404, 405}
    assert ctx["db"].query(InstagramContent).count() == 1


def test_owner_and_admin_upload_raw_but_raw_never_becomes_final(editorial_context):
    ctx = editorial_context
    enable_service(ctx)
    png = b"\x89PNG\r\n\x1a\n" + b"raw-image"
    owner_response = ctx["client"].post(
        f"{owner_base(ctx)}/raw-assets",
        files={"file": ("owner.png", png, "image/png")},
        data={"label": "Owner raw"},
    )
    assert owner_response.status_code == 201

    set_actor(ctx, ctx["admin"])
    admin_response = ctx["client"].post(
        f"{admin_base(ctx)}/raw-assets",
        files={"file": ("admin.png", png, "image/png")},
    )
    assert admin_response.status_code == 201
    assert ctx["db"].query(InstagramRawAsset).count() == 2
    assert ctx["db"].query(InstagramFinalAsset).count() == 0
    assert "/raw-assets/" in admin_response.json()["file_url"]


def test_material_change_versions_and_invalidates_but_date_change_does_not(editorial_context):
    ctx = editorial_context
    content_id, asset_id, version_id = create_content_with_asset(ctx)
    response = ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/submit-for-review")
    assert response.status_code == 200
    assert response.json()["status"] == "ready_for_review"

    set_actor(ctx, ctx["admin"])
    response = ctx["client"].post(
        f"{admin_base(ctx)}/contents/{content_id}/validate",
        json={"version_id": version_id},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "validated"
    validation = ctx["db"].query(InstagramContentValidation).one()
    assert validation.version_id == version_id
    assert validation.invalidated_at is None

    set_actor(ctx, ctx["owner"])
    response = ctx["client"].patch(
        f"{owner_base(ctx)}/contents/{content_id}/planned-date",
        json={"planned_publish_at": "2026-08-21T11:30:00+02:00"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "validated"
    assert response.json()["current_version"]["id"] == version_id
    ctx["db"].refresh(validation)
    assert validation.invalidated_at is None

    response = ctx["client"].put(
        f"{owner_base(ctx)}/contents/{content_id}/material",
        json={
            "caption": "Cambio material posterior",
            "format": "single_image",
            "asset_ids": [asset_id],
            "cover_asset_id": asset_id,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert response.json()["current_version"]["version_number"] == 3
    ctx["db"].refresh(validation)
    assert validation.invalidated_at is not None
    assert validation.invalidation_reason == "material_content_changed"


def test_validation_must_target_current_version_and_owner_requires_delegation(editorial_context):
    ctx = editorial_context
    content_id, _asset_id, version_id = create_content_with_asset(ctx)
    assert (
        ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/submit-for-review").status_code
        == 200
    )
    response = ctx["client"].post(
        f"{owner_base(ctx)}/contents/{content_id}/validate", json={"version_id": version_id}
    )
    assert response.status_code == 403

    set_actor(ctx, ctx["admin"])
    assert (
        ctx["client"]
        .patch(
            f"{admin_base(ctx)}/settings/validation-delegation",
            json={"owner_can_validate_instagram_content": True},
        )
        .status_code
        == 200
    )
    set_actor(ctx, ctx["owner"])
    response = ctx["client"].post(
        f"{owner_base(ctx)}/contents/{content_id}/validate", json={"version_id": version_id}
    )
    assert response.status_code == 200
    assert response.json()["current_version"]["validation"]["validator_role"] == "owner_delegate"

    assert (
        ctx["client"]
        .put(
            f"{owner_base(ctx)}/contents/{content_id}/material",
            json={
                "caption": "Otra versión",
                "format": "single_image",
                "asset_ids": [response.json()["current_version"]["assets"][0]["id"]],
                "cover_asset_id": response.json()["current_version"]["assets"][0]["id"],
            },
        )
        .status_code
        == 200
    )
    assert (
        ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/submit-for-review").status_code
        == 200
    )
    set_actor(ctx, ctx["admin"])
    assert (
        ctx["client"]
        .post(f"{admin_base(ctx)}/contents/{content_id}/validate", json={"version_id": version_id})
        .status_code
        == 409
    )


def test_schedule_is_blocked_without_an_approved_integration(editorial_context):
    ctx = editorial_context
    content_id, _asset_id, version_id = create_content_with_asset(ctx)
    assert (
        ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/submit-for-review").status_code
        == 200
    )
    set_actor(ctx, ctx["admin"])
    assert (
        ctx["client"]
        .post(f"{admin_base(ctx)}/contents/{content_id}/validate", json={"version_id": version_id})
        .status_code
        == 200
    )
    response = ctx["client"].post(
        f"{admin_base(ctx)}/contents/{content_id}/comments",
        json={
            "version_id": version_id,
            "kind": "change_request",
            "body": "Ajustar el tono de la llamada a la acción.",
        },
    )
    assert response.status_code == 201
    content = ctx["db"].get(InstagramContent, content_id)
    assert content.status == "changes_requested"
    validation = ctx["db"].query(InstagramContentValidation).one()
    assert validation.invalidated_at is not None

    set_actor(ctx, ctx["owner"])
    current = (
        ctx["db"]
        .query(InstagramContentVersion)
        .filter_by(content_id=content_id)
        .order_by(InstagramContentVersion.version_number.desc())
        .first()
    )
    asset_id = current.asset_links[0].asset_id
    assert (
        ctx["client"]
        .put(
            f"{owner_base(ctx)}/contents/{content_id}/material",
            json={
                "caption": "Tono ajustado",
                "format": "single_image",
                "asset_ids": [asset_id],
                "cover_asset_id": asset_id,
            },
        )
        .status_code
        == 200
    )
    submitted = (
        ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/submit-for-review").json()
    )
    set_actor(ctx, ctx["admin"])
    assert (
        ctx["client"]
        .post(
            f"{admin_base(ctx)}/contents/{content_id}/validate",
            json={"version_id": submitted["current_version"]["id"]},
        )
        .status_code
        == 200
    )
    set_actor(ctx, ctx["owner"])
    scheduled = ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/schedule")
    assert scheduled.status_code == 409
    assert ctx["db"].query(InstagramPublishJob).count() == 2
    assert (
        ctx["db"].query(InstagramPublishJob).order_by(InstagramPublishJob.id.desc()).first().status
        == "action_required"
    )
    assert ctx["db"].query(MetaIntegrationJob).count() == 0


def test_same_material_payload_does_not_create_a_version(editorial_context):
    ctx = editorial_context
    content_id, asset_id, _version_id = create_content_with_asset(ctx)
    before = ctx["db"].query(InstagramContentVersion).filter_by(content_id=content_id).count()
    response = ctx["client"].put(
        f"{owner_base(ctx)}/contents/{content_id}/material",
        json={
            "caption": "Versión lista",
            "format": "single_image",
            "asset_ids": [asset_id],
            "cover_asset_id": asset_id,
        },
    )
    assert response.status_code == 200
    after = ctx["db"].query(InstagramContentVersion).filter_by(content_id=content_id).count()
    assert after == before


def test_publish_job_endpoints_enforce_role_and_business_isolation(editorial_context):
    ctx = editorial_context
    content_id, _asset_id, _version_id = create_content_with_asset(ctx)
    set_actor(ctx, ctx["admin"])
    assert (
        ctx["client"].get(f"{admin_base(ctx)}/contents/{content_id}/publish-jobs").status_code
        == 200
    )
    assert (
        ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/publish-now").status_code
        == 403
    )


def test_owner_schedule_reschedule_publish_now_and_cancel_endpoints(editorial_context):
    ctx = editorial_context
    enable_publish_integration(ctx)
    content_id, _asset_id, version_id = create_content_with_asset(ctx)
    assert (
        ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/submit-for-review").status_code
        == 200
    )
    set_actor(ctx, ctx["admin"])
    validated = ctx["client"].post(
        f"{admin_base(ctx)}/contents/{content_id}/validate", json={"version_id": version_id}
    )
    assert validated.status_code == 200
    assert validated.json()["status"] == "scheduled"
    first_job = validated.json()["publish_jobs"][0]
    set_actor(ctx, ctx["owner"])
    future = datetime.now(timezone.utc) + timedelta(days=3)
    rescheduled = ctx["client"].patch(
        f"{owner_base(ctx)}/contents/{content_id}/publish-job/reschedule",
        json={"planned_publish_at": future.isoformat()},
    )
    assert rescheduled.status_code == 200
    assert rescheduled.json()["publish_jobs"][0]["id"] == first_job["id"]
    publish_now = ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/publish-now")
    assert publish_now.status_code == 200
    assert publish_now.json()["status"] == "queued"
    assert publish_now.json()["id"] == first_job["id"]
    cancelled = ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/publish-job/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    set_actor(ctx, ctx["admin"])
    assert (
        ctx["client"]
        .post(f"{admin_base(ctx)}/contents/{content_id}/publish-job/cancel")
        .status_code
        == 404
    )
    set_actor(ctx, ctx["other_admin"])
    assert (
        ctx["client"]
        .get(f"{admin_base(ctx, ctx['other_business'].slug)}/contents/{content_id}/publish-jobs")
        .status_code
        == 404
    )
    set_actor(ctx, ctx["staff"])
    assert (
        ctx["client"].get(f"{admin_base(ctx)}/contents/{content_id}/publish-jobs").status_code
        == 403
    )
