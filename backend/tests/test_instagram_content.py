from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
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
    InstagramContentRawAsset,
    InstagramContentSettings,
    InstagramContentValidation,
    InstagramContentVersion,
    InstagramContentVersionAsset,
    InstagramFinalAsset,
    InstagramPublishJob,
    InstagramRawAsset,
    MetaIntegrationJob,
    User,
)
from app.routers.instagram_content import admin_router, owner_router
from app.services.instagram_content_service import raw_asset_association_manager


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
            "uploads_dir": tmp_path,
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


def future_planned_at(days: int = 3) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()


def create_content_with_asset(ctx) -> tuple[int, int, int]:
    enable_service(ctx)
    response = ctx["client"].post(
        f"{owner_base(ctx)}/contents",
        json={
            "title": "Campaña de agosto",
            "caption": "Primera propuesta",
            "format": "single_image",
            "planned_publish_at": future_planned_at(),
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


def test_owner_controls_service_and_validation_without_admin_delegation(editorial_context):
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
    set_actor(ctx, ctx["admin"])
    response = ctx["client"].patch(
        f"{admin_base(ctx)}/settings/validation-delegation",
        json={"owner_can_validate_instagram_content": True},
    )
    assert response.status_code == 403
    assert {row.action for row in ctx["db"].query(AuditLog).all()} >= {
        "instagram_content_service_updated"
    }


@pytest.mark.parametrize("role", ["staff", "customer"])
def test_staff_and_customer_have_no_access(editorial_context, role):
    ctx = editorial_context
    enable_service(ctx)
    set_actor(ctx, ctx[role])
    assert ctx["client"].get(f"{admin_base(ctx)}/contents").status_code == 403
    assert ctx["client"].get(f"{owner_base(ctx)}/contents").status_code == 403


def test_owner_content_collection_contains_complete_workspace_items(editorial_context):
    ctx = editorial_context
    content_id, asset_id, _version_id = create_content_with_asset(ctx)

    response = ctx["client"].get(f"{owner_base(ctx)}/contents")

    assert response.status_code == 200
    items = response.json()["contents"]
    assert [item["id"] for item in items] == [content_id]
    assert {
        "current_version",
        "versions",
        "comments",
        "final_assets",
        "publish_jobs",
        "publication_events",
    } <= set(items[0])
    assert items[0]["current_version"]["assets"][0]["id"] == asset_id
    assert items[0]["final_assets"][0]["id"] == asset_id


def test_admin_is_isolated_to_own_business_and_cannot_create_final_content(editorial_context):
    ctx = editorial_context
    content_id, _asset_id, _version_id = create_content_with_asset(ctx)
    owner_final = ctx["client"].post(
        f"{owner_base(ctx)}/contents/{content_id}/final-assets",
        files={"file": ("owner-final.png", b"\x89PNG\r\n\x1a\nowner-final", "image/png")},
    )
    assert owner_final.status_code == 201
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
    assert (
        ctx["client"]
        .post(
            f"{admin_base(ctx, ctx['other_business'].slug)}/contents/{content_id}/editorial-review",
            json={"version_id": _version_id, "decision": "approve"},
        )
        .status_code
        == 404
    )

    set_actor(ctx, ctx["admin"])
    response = ctx["client"].post(
        f"{admin_base(ctx)}/contents",
        json={"title": "No permitido", "caption": "x", "format": "single_image"},
    )
    assert response.status_code in {404, 405}
    response = ctx["client"].post(
        f"{admin_base(ctx)}/contents/{content_id}/final-assets",
        files={"file": ("final.png", b"\x89PNG\r\n\x1a\nfinal", "image/png")},
    )
    assert response.status_code == 403
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
    set_actor(ctx, ctx["staff"])
    assert (
        ctx["client"]
        .post(
            f"{admin_base(ctx)}/raw-assets",
            files={"file": ("staff.png", png, "image/png")},
        )
        .status_code
        == 403
    )


def test_admin_editorial_review_is_separate_from_owner_technical_validation(
    editorial_context,
):
    ctx = editorial_context
    content_id, _asset_id, version_id = create_content_with_asset(ctx)
    assert (
        ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/submit-for-review").status_code
        == 200
    )

    set_actor(ctx, ctx["admin"])
    response = ctx["client"].post(
        f"{admin_base(ctx)}/contents/{content_id}/editorial-review",
        json={
            "version_id": version_id,
            "decision": "approve",
            "note": "El mensaje representa correctamente al negocio.",
        },
    )
    assert response.status_code == 201
    assert response.json()["content_status"] == "ready_for_review"
    assert ctx["db"].query(InstagramContentValidation).count() == 0
    audit = ctx["db"].query(AuditLog).filter_by(action="instagram_content_editorially_approved").one()
    assert json.loads(audit.metadata_json)["version_id"] == version_id


@pytest.mark.parametrize("role", ["admin", "staff"])
def test_business_roles_cannot_run_owner_final_operations(editorial_context, role):
    ctx = editorial_context
    content_id, _asset_id, version_id = create_content_with_asset(ctx)
    assert (
        ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/submit-for-review").status_code
        == 200
    )
    set_actor(ctx, ctx[role])

    assert (
        ctx["client"]
        .post(f"{admin_base(ctx)}/contents/{content_id}/validate", json={"version_id": version_id})
        .status_code
        == 403
    )
    assert (
        ctx["client"]
        .patch(
            f"{admin_base(ctx)}/contents/{content_id}/planned-date",
            json={"planned_publish_at": future_planned_at()},
        )
        .status_code
        == 403
    )
    for suffix in ("schedule", "publish-now", "publish-job/cancel", "publish-job/retry"):
        assert (
            ctx["client"].post(f"{admin_base(ctx)}/contents/{content_id}/{suffix}").status_code
            == 403
        )
    assert (
        ctx["client"]
        .post(
            f"{admin_base(ctx)}/contents/{content_id}/final-assets",
            files={"file": ("final.png", b"\x89PNG\r\n\x1a\nfinal", "image/png")},
        )
        .status_code
        == 403
    )

    review = ctx["client"].post(
        f"{admin_base(ctx)}/contents/{content_id}/editorial-review",
        json={"version_id": version_id, "decision": "approve"},
    )
    assert review.status_code == (201 if role == "admin" else 403)


def test_material_change_versions_and_invalidates_but_date_change_does_not(editorial_context):
    ctx = editorial_context
    content_id, asset_id, version_id = create_content_with_asset(ctx)
    response = ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/submit-for-review")
    assert response.status_code == 200
    assert response.json()["status"] == "ready_for_review"

    set_actor(ctx, ctx["owner"])
    response = ctx["client"].post(
        f"{owner_base(ctx)}/contents/{content_id}/validate",
        json={"version_id": version_id},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "validated"
    assert response.json()["current_version"]["validation"]["approved_asset_ids"] == [asset_id]
    validation = ctx["db"].query(InstagramContentValidation).one()
    assert validation.version_id == version_id
    assert validation.invalidated_at is None
    audit = ctx["db"].query(AuditLog).filter_by(action="instagram_content_validated").one()
    assert json.loads(audit.metadata_json)["approved_asset_ids"] == [asset_id]

    set_actor(ctx, ctx["owner"])
    response = ctx["client"].patch(
        f"{owner_base(ctx)}/contents/{content_id}/planned-date",
        json={"planned_publish_at": future_planned_at()},
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


def test_owner_validation_needs_no_delegation_and_admin_cannot_validate(editorial_context):
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
        == 403
    )

    set_actor(ctx, ctx["owner"])
    response = ctx["client"].post(
        f"{owner_base(ctx)}/contents/{content_id}/validate", json={"version_id": version_id}
    )
    assert response.status_code == 200
    assert response.json()["current_version"]["validation"]["validator_role"] == "owner_delegate"

    asset_id = response.json()["current_version"]["assets"][0]["id"]
    assert (
        ctx["client"]
        .put(
            f"{owner_base(ctx)}/contents/{content_id}/material",
            json={
                "caption": "Otra versión",
                "format": "single_image",
                "asset_ids": [asset_id],
                "cover_asset_id": asset_id,
            },
        )
        .status_code
        == 200
    )
    assert (
        ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/submit-for-review").status_code
        == 200
    )
    assert (
        ctx["client"]
        .post(f"{owner_base(ctx)}/contents/{content_id}/validate", json={"version_id": version_id})
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
    response = ctx["client"].post(
        f"{admin_base(ctx)}/contents/{content_id}/editorial-review",
        json={
            "version_id": version_id,
            "decision": "reject",
            "note": "Ajustar el tono de la llamada a la acción.",
        },
    )
    assert response.status_code == 201
    content = ctx["db"].get(InstagramContent, content_id)
    assert content.status == "changes_requested"
    assert ctx["db"].query(InstagramContentValidation).count() == 0

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
    approved = ctx["client"].post(
        f"{admin_base(ctx)}/contents/{content_id}/editorial-review",
        json={"version_id": submitted["current_version"]["id"], "decision": "approve"},
    )
    assert approved.status_code == 201
    assert approved.json()["content_status"] == "ready_for_review"
    set_actor(ctx, ctx["owner"])
    assert (
        ctx["client"]
        .post(
            f"{owner_base(ctx)}/contents/{content_id}/validate",
            json={"version_id": submitted["current_version"]["id"]},
        )
        .status_code
        == 200
    )
    scheduled = ctx["client"].post(f"{owner_base(ctx)}/contents/{content_id}/schedule")
    assert scheduled.status_code == 409
    assert ctx["db"].query(InstagramPublishJob).count() == 1
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
    validated = ctx["client"].post(
        f"{owner_base(ctx)}/contents/{content_id}/validate", json={"version_id": version_id}
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
    admin_publish = ctx["client"].post(f"{admin_base(ctx)}/contents/{content_id}/publish-now")
    assert admin_publish.status_code == 403
    admin_cancel = ctx["client"].post(f"{admin_base(ctx)}/contents/{content_id}/publish-job/cancel")
    assert admin_cancel.status_code == 403
    metrics = ctx["client"].get(f"{admin_base(ctx)}/publication-metrics")
    assert metrics.status_code == 200
    assert set(metrics.json()) >= {
        "drafts",
        "approved",
        "scheduled",
        "published",
        "failed",
        "publish_success_rate",
    }
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
    assert (
        ctx["client"].post(f"{admin_base(ctx)}/contents/{content_id}/publish-now").status_code
        == 403
    )


@pytest.mark.parametrize(
    "status",
    ["draft", "changes_requested", "cancelled", "ready_for_review", "validated"],
)
def test_owner_physically_deletes_unpublished_content_and_orphan_files(
    editorial_context, status
):
    ctx = editorial_context
    content_id, asset_id, _version_id = create_content_with_asset(ctx)
    content = ctx["db"].get(InstagramContent, content_id)
    content.status = status
    asset = ctx["db"].get(InstagramFinalAsset, asset_id)
    asset_path = ctx["uploads_dir"] / asset.storage_key
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(b"final-asset")
    ctx["db"].commit()

    response = ctx["client"].delete(f"{owner_base(ctx)}/contents/{content_id}")

    assert response.status_code == 200
    assert response.json() == {
        "id": content_id,
        "disposition": "deleted",
        "previous_status": status,
    }
    assert ctx["db"].get(InstagramContent, content_id) is None
    assert ctx["db"].get(InstagramFinalAsset, asset_id) is None
    assert not asset_path.exists()
    audit = ctx["db"].query(AuditLog).filter_by(action="content_deleted").one()
    metadata = json.loads(audit.metadata_json)
    assert metadata["previous_status"] == status
    assert metadata["review_cancelled"] is (status == "ready_for_review")


@pytest.mark.parametrize(
    ("status", "job_status", "expected_action"),
    [
        ("scheduled", "queued", "scheduled_content_removed"),
        ("published", "published", "content_archived"),
    ],
)
def test_owner_archives_historical_content_and_preserves_publish_identity(
    editorial_context, status, job_status, expected_action
):
    ctx = editorial_context
    content_id, _asset_id, version_id = create_content_with_asset(ctx)
    content = ctx["db"].get(InstagramContent, content_id)
    content.status = status
    job = InstagramPublishJob(
        business_id=ctx["business"].id,
        content_item_id=content_id,
        content_version_id=version_id,
        status=job_status,
        scheduled_for=datetime.now(timezone.utc) + timedelta(hours=1),
        attempt_count=1,
        max_attempts=3,
        idempotency_key=f"archive-{status}-{content_id}",
        provider_container_id="provider-container-preserved",
        provider_media_id="provider-media-preserved" if status == "published" else None,
        provider_permalink="https://instagram.example/p/preserved" if status == "published" else None,
    )
    ctx["db"].add(job)
    ctx["db"].commit()
    job_id = job.id

    response = ctx["client"].delete(f"{owner_base(ctx)}/contents/{content_id}")

    assert response.status_code == 200
    assert response.json()["disposition"] == "archived"
    ctx["db"].expire_all()
    stored_content = ctx["db"].get(InstagramContent, content_id)
    stored_job = ctx["db"].get(InstagramPublishJob, job_id)
    assert stored_content.archived_at is not None
    assert stored_job.provider_container_id == "provider-container-preserved"
    if status == "scheduled":
        assert stored_content.status == "cancelled"
        assert stored_job.status == "cancelled"
        assert (
            ctx["db"]
            .query(AuditLog)
            .filter_by(action="publish_job_cancelled_by_delete", resource_id=job_id)
            .count()
            == 1
        )
    else:
        assert stored_content.status == "published"
        assert stored_job.status == "published"
        assert stored_job.provider_media_id == "provider-media-preserved"
    assert ctx["db"].query(AuditLog).filter_by(action=expected_action).count() == 1
    assert ctx["client"].get(f"{owner_base(ctx)}/contents/{content_id}").status_code == 404
    assert ctx["client"].get(f"{owner_base(ctx)}/contents").json()["contents"] == []


def test_owner_removal_returns_conflict_when_publication_has_started(editorial_context):
    ctx = editorial_context
    content_id, _asset_id, version_id = create_content_with_asset(ctx)
    content = ctx["db"].get(InstagramContent, content_id)
    content.status = "scheduled"
    job = InstagramPublishJob(
        business_id=ctx["business"].id,
        content_item_id=content_id,
        content_version_id=version_id,
        status="publishing",
        scheduled_for=datetime.now(timezone.utc),
        attempt_count=1,
        max_attempts=3,
        idempotency_key=f"publishing-{content_id}",
        provider_container_id="in-flight-container",
    )
    ctx["db"].add(job)
    ctx["db"].commit()

    response = ctx["client"].delete(f"{owner_base(ctx)}/contents/{content_id}")

    assert response.status_code == 409
    assert "publicación ya había comenzado" in response.json()["detail"]
    ctx["db"].expire_all()
    assert ctx["db"].get(InstagramContent, content_id).archived_at is None
    assert ctx["db"].get(InstagramPublishJob, job.id).status == "publishing"
    assert ctx["db"].query(AuditLog).filter_by(action="scheduled_content_removed").count() == 0


def test_owner_deletes_unused_raw_asset_but_blocks_referenced_material(editorial_context):
    ctx = editorial_context
    enable_service(ctx)
    unused = ctx["client"].post(
        f"{owner_base(ctx)}/raw-assets",
        files={"file": ("unused.png", b"\x89PNG\r\n\x1a\nunused", "image/png")},
        data={"label": "Sin uso"},
    )
    assert unused.status_code == 201
    unused_id = unused.json()["id"]
    unused_asset = ctx["db"].get(InstagramRawAsset, unused_id)
    unused_path = ctx["uploads_dir"] / unused_asset.storage_key
    assert unused_path.exists()

    empty_manager = ctx["client"].get(
        f"{owner_base(ctx)}/raw-assets/{unused_id}/associations"
    )
    assert empty_manager.status_code == 200
    assert empty_manager.json()["association_count"] == 0
    assert empty_manager.json()["associations"] == []

    deleted = ctx["client"].delete(f"{owner_base(ctx)}/raw-assets/{unused_id}")
    assert deleted.status_code == 200
    assert ctx["db"].get(InstagramRawAsset, unused_id) is None
    assert not unused_path.exists()
    assert ctx["db"].query(AuditLog).filter_by(action="raw_asset_deleted").count() == 1

    referenced = ctx["client"].post(
        f"{owner_base(ctx)}/raw-assets",
        files={"file": ("used.png", b"\x89PNG\r\n\x1a\nused", "image/png")},
    )
    referenced_id = referenced.json()["id"]
    content_id, _asset_id, _version_id = create_content_with_asset(ctx)
    version = (
        ctx["db"]
        .query(InstagramContentVersion)
        .filter_by(content_id=content_id)
        .order_by(InstagramContentVersion.version_number.desc())
        .first()
    )
    version.editorial_package_json = json.dumps(
        {
            "asset_plan": {
                "recommended": [{"source": "instagram_raw_asset", "id": referenced_id}]
            }
        }
    )
    ctx["db"].commit()

    blocked = ctx["client"].delete(f"{owner_base(ctx)}/raw-assets/{referenced_id}")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "raw_asset_in_use"
    assert "está siendo utilizado" in blocked.json()["detail"]["message"]
    assert ctx["db"].get(InstagramRawAsset, referenced_id) is not None


def test_shared_final_asset_forces_archive_and_preserves_shared_link(editorial_context):
    ctx = editorial_context
    content_id, asset_id, _version_id = create_content_with_asset(ctx)
    asset = ctx["db"].get(InstagramFinalAsset, asset_id)
    asset_path = ctx["uploads_dir"] / asset.storage_key
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(b"shared-final")
    second = ctx["client"].post(
        f"{owner_base(ctx)}/contents",
        json={"title": "Segundo", "caption": "Usa asset compartido", "format": "single_image"},
    ).json()
    second_version_id = second["current_version"]["id"]
    ctx["db"].add(
        InstagramContentVersionAsset(
            version_id=second_version_id,
            asset_id=asset_id,
            position=0,
            is_cover=True,
        )
    )
    ctx["db"].commit()

    response = ctx["client"].delete(f"{owner_base(ctx)}/contents/{content_id}")

    assert response.status_code == 200
    assert response.json()["disposition"] == "archived"
    assert ctx["db"].get(InstagramContent, content_id).archived_at is not None
    assert ctx["db"].get(InstagramFinalAsset, asset_id) is not None
    assert (
        ctx["db"]
        .query(InstagramContentVersionAsset)
        .filter_by(version_id=second_version_id, asset_id=asset_id)
        .count()
        == 1
    )
    assert asset_path.exists()


@pytest.mark.parametrize("role", ["admin", "staff"])
def test_admin_and_staff_cannot_remove_instagram_material(editorial_context, role):
    ctx = editorial_context
    content_id, _asset_id, _version_id = create_content_with_asset(ctx)
    set_actor(ctx, ctx[role])

    assert ctx["client"].delete(f"{owner_base(ctx)}/contents/{content_id}").status_code == 403
    assert ctx["client"].delete(f"{admin_base(ctx)}/contents/{content_id}").status_code == 403


def test_owner_removal_is_isolated_by_business(editorial_context):
    ctx = editorial_context
    content_id, _asset_id, _version_id = create_content_with_asset(ctx)
    raw = ctx["client"].post(
        f"{owner_base(ctx)}/raw-assets",
        files={"file": ("isolated.png", b"\x89PNG\r\n\x1a\nisolated", "image/png")},
    ).json()
    ctx["db"].add(
        InstagramContentSettings(business_id=ctx["other_business"].id, enabled=True)
    )
    ctx["db"].commit()
    other_base = (
        f"/api/owner/businesses/{ctx['other_business'].id}/instagram-content"
    )

    assert ctx["client"].delete(f"{other_base}/contents/{content_id}").status_code == 404
    assert ctx["client"].delete(f"{other_base}/raw-assets/{raw['id']}").status_code == 404
    assert ctx["db"].get(InstagramContent, content_id) is not None
    assert ctx["db"].get(InstagramRawAsset, raw["id"]) is not None


def upload_raw_asset(ctx, filename: str = "foto-cliente.png") -> dict:
    enable_service(ctx)
    response = ctx["client"].post(
        f"{owner_base(ctx)}/raw-assets",
        files={"file": (filename, b"\x89PNG\r\n\x1a\nraw-source", "image/png")},
        data={"label": "Foto cliente"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize(
    ("filename", "content", "media_type", "code", "message"),
    (
        (
            "material.gif",
            b"GIF89a",
            "image/gif",
            "unsupported_file_type",
            "Este tipo de archivo no está permitido",
        ),
        ("vacio.png", b"", "image/png", "empty_file", "El archivo está vacío"),
        (
            "falso.png",
            b"not-a-png",
            "image/png",
            "invalid_image_content",
            "no corresponde a una imagen válida",
        ),
    ),
)
def test_raw_upload_returns_safe_specific_errors(
    editorial_context,
    filename,
    content,
    media_type,
    code,
    message,
):
    ctx = editorial_context
    enable_service(ctx)

    response = ctx["client"].post(
        f"{owner_base(ctx)}/raw-assets",
        files={"file": (filename, content, media_type)},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == code
    assert message in response.json()["detail"]["message"]
    assert ctx["db"].query(InstagramRawAsset).count() == 0


def test_raw_upload_reports_dynamic_size_limit(editorial_context, monkeypatch):
    ctx = editorial_context
    enable_service(ctx)
    monkeypatch.setattr("app.routers.instagram_content.MAX_ASSET_BYTES", 8)

    response = ctx["client"].post(
        f"{owner_base(ctx)}/raw-assets",
        files={"file": ("grande.png", b"123456789", "image/png")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == {
        "code": "upload_too_large",
        "message": "El archivo supera el tamaño máximo permitido de 5 MB.",
    }


def test_final_upload_uses_the_same_safe_validation_contract(editorial_context):
    ctx = editorial_context
    content_id, _asset_id, _version_id = create_content_with_asset(ctx)

    response = ctx["client"].post(
        f"{owner_base(ctx)}/contents/{content_id}/final-assets",
        files={"file": ("falso.webp", b"not-a-webp", "image/webp")},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_image_content"


def test_owner_previews_and_downloads_raw_asset_with_safe_original_name(editorial_context):
    ctx = editorial_context
    raw = upload_raw_asset(ctx, 'carpeta/cliente"final.png')

    preview = ctx["client"].get(f"{owner_base(ctx)}/raw-assets/{raw['id']}/file")
    download = ctx["client"].get(f"{owner_base(ctx)}/raw-assets/{raw['id']}/download")

    assert preview.status_code == 200
    assert preview.content == b"\x89PNG\r\n\x1a\nraw-source"
    assert preview.headers["content-type"] == "image/png"
    assert download.status_code == 200
    assert download.content == preview.content
    assert download.headers["content-type"] == "image/png"
    disposition = download.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "cliente" in disposition
    assert "final.png" in disposition
    assert '"final.png"' not in disposition


def test_owner_associates_disassociates_and_creates_content_from_raw(editorial_context):
    ctx = editorial_context
    raw = upload_raw_asset(ctx)
    content_id, _asset_id, _version_id = create_content_with_asset(ctx)

    associated = ctx["client"].post(
        f"{owner_base(ctx)}/raw-assets/{raw['id']}/associations",
        json={"content_id": content_id},
    )

    assert associated.status_code == 200
    assert [item["id"] for item in associated.json()["content"]["source_assets"]] == [raw["id"]]
    assert associated.json()["raw_asset"]["associations"][0]["content_id"] == content_id
    assert ctx["db"].query(InstagramContentRawAsset).count() == 1
    assert ctx["db"].query(AuditLog).filter_by(action="raw_asset_associated").count() == 1

    removed = ctx["client"].delete(
        f"{owner_base(ctx)}/raw-assets/{raw['id']}/associations/{content_id}"
    )
    assert removed.status_code == 200
    assert removed.json()["content"]["source_assets"] == []
    assert removed.json()["raw_asset"]["associations"] == []
    assert ctx["db"].query(InstagramContentRawAsset).count() == 0
    assert ctx["db"].query(AuditLog).filter_by(action="raw_asset_disassociated").count() == 1

    created = ctx["client"].post(
        f"{owner_base(ctx)}/raw-assets/{raw['id']}/create-content"
    )
    assert created.status_code == 201
    assert created.json()["content"]["status"] == "draft"
    assert created.json()["content"]["final_assets"] == []
    assert created.json()["content"]["source_assets"][0]["id"] == raw["id"]


def test_raw_asset_association_manager_describes_and_batches_only_safe_links(
    editorial_context,
):
    ctx = editorial_context
    raw = upload_raw_asset(ctx)

    def create_draft(title: str) -> int:
        response = ctx["client"].post(
            f"{owner_base(ctx)}/contents",
            json={"title": title, "caption": "", "format": "single_image"},
        )
        assert response.status_code == 201
        return response.json()["id"]

    draft_ids = [create_draft("Borrador A"), create_draft("Borrador B")]
    protected_id = create_draft("Promo validada")
    for content_id in [*draft_ids, protected_id]:
        response = ctx["client"].post(
            f"{owner_base(ctx)}/raw-assets/{raw['id']}/associations",
            json={"content_id": content_id},
        )
        assert response.status_code == 200

    final = InstagramFinalAsset(
        business_id=ctx["business"].id,
        content_id=protected_id,
        uploaded_by_user_id=ctx["owner"].id,
        source_raw_asset_id=raw["id"],
        original_filename="derivado.png",
        storage_key=f"_instagram_content/{ctx['business'].id}/final/derivado.png",
        media_type="image/png",
        size_bytes=12,
    )
    protected = ctx["db"].get(InstagramContent, protected_id)
    protected.status = "validated"
    protected.versions[-1].editorial_package_json = json.dumps(
        {"asset_plan": {"recommended": [{"source": "instagram_raw_asset", "id": raw["id"]}]}}
    )
    ctx["db"].add(final)
    ctx["db"].commit()

    manager_response = ctx["client"].get(
        f"{owner_base(ctx)}/raw-assets/{raw['id']}/associations"
    )
    assert manager_response.status_code == 200
    manager = manager_response.json()
    assert manager["association_count"] == 3
    assert manager["modifiable_count"] == 2
    protected_association = next(
        item for item in manager["associations"] if item["content_id"] == protected_id
    )
    assert protected_association == {
        "content_id": protected_id,
        "content_title": "Promo validada",
        "content_status": "validated",
        "content_archived": False,
        "is_source_material": True,
        "has_final_derivative": True,
        "has_historical_reference": True,
        "modifiable": False,
        "protected_reason": "Existe un material final cuya procedencia depende de este archivo.",
    }

    blocked = ctx["client"].delete(f"{owner_base(ctx)}/raw-assets/{raw['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["associations"] == manager["associations"]

    batch = ctx["client"].delete(
        f"{owner_base(ctx)}/raw-assets/{raw['id']}/associations"
    )
    assert batch.status_code == 200
    assert {item["id"] for item in batch.json()["contents"]} == set(draft_ids)
    assert batch.json()["association_manager"]["association_count"] == 1
    assert batch.json()["association_manager"]["modifiable_count"] == 0
    remaining_ids = {
        row.content_id
        for row in ctx["db"].query(InstagramContentRawAsset).filter_by(raw_asset_id=raw["id"])
    }
    assert remaining_ids == {protected_id}
    assert (
        ctx["db"]
        .query(AuditLog)
        .filter_by(action="raw_asset_associations_disassociated")
        .count()
        == 1
    )
    assert (
        ctx["client"]
        .delete(f"{owner_base(ctx)}/raw-assets/{raw['id']}/associations/{protected_id}")
        .status_code
        == 409
    )


def test_raw_asset_association_manager_is_owner_only_and_business_isolated(editorial_context):
    ctx = editorial_context
    raw = upload_raw_asset(ctx)
    ctx["db"].add(InstagramContentSettings(business_id=ctx["other_business"].id, enabled=True))
    ctx["db"].commit()
    other_base = f"/api/owner/businesses/{ctx['other_business'].id}/instagram-content"

    assert ctx["client"].get(f"{other_base}/raw-assets/{raw['id']}/associations").status_code == 404
    assert ctx["client"].delete(f"{other_base}/raw-assets/{raw['id']}/associations").status_code == 404

    set_actor(ctx, ctx["admin"])
    assert (
        ctx["client"].get(f"{owner_base(ctx)}/raw-assets/{raw['id']}/associations").status_code
        == 403
    )
    assert (
        ctx["client"].get(f"{admin_base(ctx)}/raw-assets/{raw['id']}/associations").status_code
        == 403
    )


def test_raw_asset_association_manager_uses_constant_queries(editorial_context):
    ctx = editorial_context
    raw = upload_raw_asset(ctx)
    for index in range(4):
        content = ctx["client"].post(
            f"{owner_base(ctx)}/contents",
            json={"title": f"Contenido {index}", "caption": "", "format": "single_image"},
        ).json()
        assert (
            ctx["client"]
            .post(
                f"{owner_base(ctx)}/raw-assets/{raw['id']}/associations",
                json={"content_id": content["id"]},
            )
            .status_code
            == 200
        )

    statements = []

    def count_statement(*_args):
        statements.append(1)

    event.listen(ctx["db"].bind, "before_cursor_execute", count_statement)
    try:
        manager = raw_asset_association_manager(
            ctx["db"], business_id=ctx["business"].id, asset_id=raw["id"]
        )
    finally:
        event.remove(ctx["db"].bind, "before_cursor_execute", count_statement)

    assert manager["association_count"] == 4
    assert len(statements) <= 7


def test_owner_cannot_disassociate_historical_or_final_source(editorial_context):
    ctx = editorial_context
    raw = upload_raw_asset(ctx)
    content_id, _asset_id, _version_id = create_content_with_asset(ctx)
    assert (
        ctx["client"]
        .post(
            f"{owner_base(ctx)}/raw-assets/{raw['id']}/associations",
            json={"content_id": content_id},
        )
        .status_code
        == 200
    )
    content = ctx["db"].get(InstagramContent, content_id)
    content.status = "validated"
    ctx["db"].commit()

    historical = ctx["client"].delete(
        f"{owner_base(ctx)}/raw-assets/{raw['id']}/associations/{content_id}"
    )
    assert historical.status_code == 409
    assert "borradores" in historical.json()["detail"]
    assert ctx["db"].query(InstagramContentRawAsset).count() == 1

    content.status = "draft"
    ctx["db"].commit()
    used = ctx["client"].post(
        f"{owner_base(ctx)}/raw-assets/{raw['id']}/use-as-final",
        json={"content_id": content_id},
    )
    assert used.status_code == 201
    blocked = ctx["client"].delete(
        f"{owner_base(ctx)}/raw-assets/{raw['id']}/associations/{content_id}"
    )
    assert blocked.status_code == 409
    assert "trazabilidad" in blocked.json()["detail"]


def test_owner_uses_raw_as_final_with_copy_provenance_and_delete_protection(
    editorial_context,
):
    ctx = editorial_context
    raw = upload_raw_asset(ctx)
    raw_row = ctx["db"].get(InstagramRawAsset, raw["id"])
    raw_path = ctx["uploads_dir"] / raw_row.storage_key
    content_id, _asset_id, _version_id = create_content_with_asset(ctx)

    response = ctx["client"].post(
        f"{owner_base(ctx)}/raw-assets/{raw['id']}/use-as-final",
        json={"content_id": content_id},
    )

    assert response.status_code == 201
    derived = [
        item
        for item in response.json()["content"]["final_assets"]
        if item["source_raw_asset_id"] == raw["id"]
    ]
    assert len(derived) == 1
    final_row = ctx["db"].get(InstagramFinalAsset, derived[0]["id"])
    final_path = ctx["uploads_dir"] / final_row.storage_key
    assert final_path != raw_path
    assert final_path.read_bytes() == raw_path.read_bytes()
    assert ctx["db"].query(AuditLog).filter_by(action="raw_asset_used_as_final").count() == 1

    blocked_delete = ctx["client"].delete(f"{owner_base(ctx)}/raw-assets/{raw['id']}")
    assert blocked_delete.status_code == 409
    assert raw_path.exists()
    assert final_path.exists()

    removed_content = ctx["client"].delete(f"{owner_base(ctx)}/contents/{content_id}")
    assert removed_content.status_code == 200
    assert ctx["db"].query(InstagramContentRawAsset).filter_by(raw_asset_id=raw["id"]).count() == 0
    assert not final_path.exists()
    removed_raw = ctx["client"].delete(f"{owner_base(ctx)}/raw-assets/{raw['id']}")
    assert removed_raw.status_code == 200
    assert not raw_path.exists()


def test_use_as_final_rejects_invalid_stored_media(editorial_context):
    ctx = editorial_context
    enable_service(ctx)
    storage_key = f"_instagram_content/{ctx['business'].id}/raw/invalid.gif"
    path = ctx["uploads_dir"] / storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"GIF89a-invalid")
    raw = InstagramRawAsset(
        business_id=ctx["business"].id,
        uploaded_by_user_id=ctx["owner"].id,
        original_filename="invalid.gif",
        storage_key=storage_key,
        media_type="image/gif",
        size_bytes=14,
    )
    ctx["db"].add(raw)
    ctx["db"].commit()
    content_id, _asset_id, _version_id = create_content_with_asset(ctx)

    response = ctx["client"].post(
        f"{owner_base(ctx)}/raw-assets/{raw.id}/use-as-final",
        json={"content_id": content_id},
    )

    assert response.status_code == 400
    assert ctx["db"].query(InstagramContentRawAsset).filter_by(raw_asset_id=raw.id).count() == 0
    assert (
        ctx["db"].query(InstagramFinalAsset).filter_by(source_raw_asset_id=raw.id).count() == 0
    )


def test_raw_library_operations_block_cross_business_idor(editorial_context):
    ctx = editorial_context
    raw = upload_raw_asset(ctx)
    ctx["db"].add(InstagramContentSettings(business_id=ctx["other_business"].id, enabled=True))
    ctx["db"].commit()
    other_base = f"/api/owner/businesses/{ctx['other_business'].id}/instagram-content"
    other_content = ctx["client"].post(
        f"{other_base}/contents",
        json={"title": "Otro negocio", "caption": "", "format": "single_image"},
    ).json()

    assert ctx["client"].get(f"{other_base}/raw-assets/{raw['id']}/file").status_code == 404
    assert (
        ctx["client"].get(f"{other_base}/raw-assets/{raw['id']}/download").status_code == 404
    )
    assert (
        ctx["client"]
        .post(
            f"{owner_base(ctx)}/raw-assets/{raw['id']}/associations",
            json={"content_id": other_content["id"]},
        )
        .status_code
        == 404
    )
    assert (
        ctx["client"]
        .post(
            f"{owner_base(ctx)}/raw-assets/{raw['id']}/use-as-final",
            json={"content_id": other_content["id"]},
        )
        .status_code
        == 404
    )


@pytest.mark.parametrize("role", ["admin", "staff"])
def test_admin_and_staff_get_no_owner_raw_library_privileges(editorial_context, role):
    ctx = editorial_context
    raw = upload_raw_asset(ctx)
    content_id, _asset_id, _version_id = create_content_with_asset(ctx)
    set_actor(ctx, ctx[role])

    assert (
        ctx["client"]
        .post(
            f"{owner_base(ctx)}/raw-assets/{raw['id']}/use-as-final",
            json={"content_id": content_id},
        )
        .status_code
        == 403
    )
    assert (
        ctx["client"]
        .post(
            f"{admin_base(ctx)}/raw-assets/{raw['id']}/use-as-final",
            json={"content_id": content_id},
        )
        .status_code
        == 403
    )
