from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.models import (
    AuditLog,
    Business,
    BusinessChannelControl,
    BusinessChannelIntegration,
    InstagramContent,
    InstagramContentSettings,
    InstagramContentValidation,
    InstagramContentVersion,
    InstagramContentVersionAsset,
    InstagramFinalAsset,
    InstagramPublishJob,
    User,
)
from app.services.instagram_publish_service import (
    build_publish_claim_statement,
    cancel_business_jobs,
    cancel_publish_job,
    claim_publish_jobs,
    normalize_planned_datetime,
    stable_idempotency_key,
    sync_publish_job,
    utc_now,
)
from app.services.instagram_publishing_adapter import SimulatedInstagramPublishingAdapter
from app.workers.instagram_publish_worker import InstagramPublishWorker


@pytest.fixture
def publishing_context():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    business = Business(slug="publish-a", name="Publish A", timezone="Europe/Madrid")
    other = Business(slug="publish-b", name="Publish B", timezone="Europe/Madrid")
    owner = User(email="publisher-owner@example.test", is_owner=True)
    db.add_all([business, other, owner])
    db.flush()
    db.add(InstagramContentSettings(business_id=business.id, enabled=True))
    db.add(
        BusinessChannelControl(
            business_id=business.id,
            channel="instagram",
            status="approved",
            integrated_delivery_enabled=True,
            connector_policy="owner_only",
        )
    )
    integration = BusinessChannelIntegration(
        business_id=business.id,
        channel="instagram",
        provider="instagram",
        external_account_id="ig-publish-a",
        integration_status="connected",
        health_status="healthy",
    )
    db.add(integration)
    db.commit()
    yield {
        "db": db,
        "factory": factory,
        "business": business,
        "other": other,
        "owner": owner,
        "integration": integration,
    }
    db.close()
    engine.dispose()


def make_validated_content(ctx: dict, *, planned: datetime | None = None) -> InstagramContent:
    db: Session = ctx["db"]
    content = InstagramContent(
        business_id=ctx["business"].id,
        title="Publicación simulada",
        status="validated",
        planned_publish_at=planned or (utc_now() + timedelta(hours=2)),
        created_by_user_id=ctx["owner"].id,
    )
    db.add(content)
    db.flush()
    asset = InstagramFinalAsset(
        business_id=content.business_id,
        content_id=content.id,
        uploaded_by_user_id=ctx["owner"].id,
        original_filename="final.png",
        storage_key=f"_instagram_content/{content.business_id}/final/{content.id}.png",
        media_type="image/png",
        size_bytes=10,
    )
    version = InstagramContentVersion(
        business_id=content.business_id,
        content_id=content.id,
        version_number=1,
        caption="Caption final",
        format="single_image",
        created_by_user_id=ctx["owner"].id,
    )
    db.add_all([asset, version])
    db.flush()
    db.add(
        InstagramContentVersionAsset(
            version_id=version.id, asset_id=asset.id, position=0, is_cover=True
        )
    )
    db.add(
        InstagramContentValidation(
            business_id=content.business_id,
            content_id=content.id,
            version_id=version.id,
            validated_by_user_id=ctx["owner"].id,
            validator_role="owner_delegate",
            validated_at=utc_now(),
        )
    )
    db.commit()
    return content


def worker_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "instagram_publishing_worker_enabled": True,
        "instagram_publishing_simulated_mode": True,
        "instagram_publishing_claim_ttl_seconds": 30,
        "instagram_publishing_backoff_base_seconds": 1,
        "instagram_publishing_backoff_max_seconds": 10,
        "instagram_publishing_max_attempts": 3,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def queue_now(ctx: dict) -> InstagramPublishJob:
    content = make_validated_content(ctx)
    job = sync_publish_job(ctx["db"], content, actor=ctx["owner"], now=utc_now(), force_now=True)
    ctx["db"].commit()
    return job


def test_local_times_are_normalized_to_utc_and_dst_edges_are_rejected():
    normal = normalize_planned_datetime(datetime(2026, 8, 20, 10, 0), "Europe/Madrid")
    assert normal == datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)
    with pytest.raises(HTTPException, match="does not exist"):
        normalize_planned_datetime(datetime(2026, 3, 29, 2, 30), "Europe/Madrid")
    with pytest.raises(HTTPException, match="Ambiguous"):
        normalize_planned_datetime(datetime(2026, 10, 25, 2, 30), "Europe/Madrid")
    explicit = normalize_planned_datetime(
        datetime(2026, 10, 25, 2, 30, tzinfo=timezone(timedelta(hours=1))),
        "Europe/Madrid",
    )
    assert explicit == datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)


def test_scheduler_is_idempotent_and_date_change_preserves_validation(publishing_context):
    ctx = publishing_context
    content = make_validated_content(ctx)
    first = sync_publish_job(ctx["db"], content, actor=ctx["owner"])
    ctx["db"].commit()
    validation = ctx["db"].query(InstagramContentValidation).one()
    original_validation_id = validation.id
    content.planned_publish_at = utc_now() + timedelta(hours=4)
    second = sync_publish_job(ctx["db"], content, actor=ctx["owner"])
    ctx["db"].commit()
    assert second.id == first.id
    assert second.idempotency_key == stable_idempotency_key(
        content.business_id, content.id, second.content_version_id
    )
    assert ctx["db"].query(InstagramPublishJob).count() == 1
    assert ctx["db"].get(InstagramContentValidation, original_validation_id).invalidated_at is None


def test_past_date_and_unavailable_integration_create_no_executable_job(publishing_context):
    ctx = publishing_context
    content = make_validated_content(ctx, planned=utc_now() - timedelta(minutes=1))
    job = sync_publish_job(ctx["db"], content, actor=ctx["owner"])
    assert job.status == "action_required"
    assert job.provider_error_code == "planned_date_in_past"
    content.planned_publish_at = utc_now() + timedelta(hours=1)
    ctx["integration"].health_status = "action_required"
    job = sync_publish_job(ctx["db"], content, actor=ctx["owner"])
    assert job.status == "action_required"
    assert job.provider_error_code == "instagram_integration_health_blocking"


def test_scheduler_does_not_create_job_for_unvalidated_version(publishing_context):
    ctx = publishing_context
    content = make_validated_content(ctx)
    validation = ctx["db"].query(InstagramContentValidation).filter_by(content_id=content.id).one()
    validation.invalidated_at = utc_now()
    ctx["db"].commit()
    with pytest.raises(HTTPException, match="not validated"):
        sync_publish_job(ctx["db"], content, actor=ctx["owner"])
    assert ctx["db"].query(InstagramPublishJob).count() == 0


def test_claim_is_single_and_expired_claim_is_recovered(publishing_context):
    ctx = publishing_context
    job = queue_now(ctx)
    clock = utc_now()
    claimed = claim_publish_jobs(
        ctx["db"], worker_id="worker-a", limit=1, claim_ttl_seconds=30, now=clock
    )
    ctx["db"].commit()
    assert [item.id for item in claimed] == [job.id]
    assert (
        claim_publish_jobs(
            ctx["db"], worker_id="worker-b", limit=1, claim_ttl_seconds=30, now=clock
        )
        == []
    )
    recovered = claim_publish_jobs(
        ctx["db"],
        worker_id="worker-b",
        limit=1,
        claim_ttl_seconds=30,
        now=clock + timedelta(seconds=31),
    )
    ctx["db"].commit()
    assert [item.id for item in recovered] == [job.id]
    assert recovered[0].attempt_count == 2
    assert (
        ctx["db"].query(AuditLog).filter_by(action="publish_expired_claim_recovered").count() == 1
    )


def test_expired_claim_after_execution_is_not_retried(publishing_context):
    ctx = publishing_context
    job = queue_now(ctx)
    job.status = "simulating_publish"
    job.claimed_by = "dead-worker"
    job.claimed_at = utc_now() - timedelta(minutes=2)
    job.claim_expires_at = utc_now() - timedelta(minutes=1)
    ctx["db"].commit()
    claimed = claim_publish_jobs(ctx["db"], worker_id="replacement", limit=1, claim_ttl_seconds=30)
    ctx["db"].commit()
    assert claimed == []
    assert job.status == "action_required"
    assert job.provider_status == "unknown_after_claim_expiry"


def test_postgresql_claim_statement_uses_skip_locked():
    statement = build_publish_claim_statement(clock=utc_now(), limit=5, dialect_name="postgresql")
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql


@pytest.mark.parametrize(
    ("behavior", "expected_status"),
    [
        ("success", "published"),
        ("delayed_success", "published"),
        ("temporary_error", "retry_wait"),
        ("permanent_error", "failed"),
        ("timeout", "retry_wait"),
        ("unknown_result", "action_required"),
    ],
)
def test_worker_handles_simulated_outcomes(publishing_context, behavior, expected_status):
    ctx = publishing_context
    job = queue_now(ctx)
    worker = InstagramPublishWorker(
        settings=worker_settings(),
        session_factory=ctx["factory"],
        adapter=SimulatedInstagramPublishingAdapter(behavior=behavior),
        worker_id=f"worker-{behavior}",
    )
    assert worker.run_once() == 1
    ctx["db"].expire_all()
    stored = ctx["db"].get(InstagramPublishJob, job.id)
    assert stored.status == expected_status
    if expected_status == "published":
        assert stored.provider_media_id
        assert ctx["db"].get(InstagramContent, job.content_item_id).status == "published"


def test_retry_reuses_same_job_and_provider_identity(publishing_context):
    ctx = publishing_context
    job = queue_now(ctx)
    worker = InstagramPublishWorker(
        settings=worker_settings(),
        session_factory=ctx["factory"],
        adapter=SimulatedInstagramPublishingAdapter(behavior="temporary_error"),
        worker_id="retry-worker",
    )
    worker.run_once()
    ctx["db"].expire_all()
    stored = ctx["db"].get(InstagramPublishJob, job.id)
    stored.next_attempt_at = utc_now() - timedelta(seconds=1)
    ctx["db"].commit()
    worker.adapter = SimulatedInstagramPublishingAdapter(behavior="duplicate_response")
    worker.run_once()
    ctx["db"].expire_all()
    stored = ctx["db"].get(InstagramPublishJob, job.id)
    assert stored.status == "published"
    assert stored.attempt_count == 2
    assert ctx["db"].query(InstagramPublishJob).count() == 1
    assert stored.provider_status == "duplicate_idempotent"


def test_attempt_limit_finishes_as_failed(publishing_context):
    ctx = publishing_context
    job = queue_now(ctx)
    job.max_attempts = 1
    ctx["db"].commit()
    worker = InstagramPublishWorker(
        settings=worker_settings(),
        session_factory=ctx["factory"],
        adapter=SimulatedInstagramPublishingAdapter(behavior="temporary_error"),
        worker_id="last-attempt-worker",
    )
    worker.run_once()
    ctx["db"].expire_all()
    stored = ctx["db"].get(InstagramPublishJob, job.id)
    assert stored.status == "failed"
    assert stored.provider_status == "attempts_exhausted"


def test_unknown_outcome_cannot_be_rescheduled_into_a_duplicate(publishing_context):
    ctx = publishing_context
    job = queue_now(ctx)
    worker = InstagramPublishWorker(
        settings=worker_settings(),
        session_factory=ctx["factory"],
        adapter=SimulatedInstagramPublishingAdapter(behavior="unknown_result"),
        worker_id="unknown-worker",
    )
    worker.run_once()
    ctx["db"].expire_all()
    content = ctx["db"].get(InstagramContent, job.content_item_id)
    with pytest.raises(HTTPException, match="manual review"):
        sync_publish_job(ctx["db"], content, actor=ctx["owner"], now=utc_now(), force_now=True)
    assert ctx["db"].query(InstagramPublishJob).count() == 1
    assert ctx["db"].get(InstagramPublishJob, job.id).status == "action_required"


def test_material_cancellation_and_executing_claim_require_manual_action(publishing_context):
    ctx = publishing_context
    content = make_validated_content(ctx)
    job = sync_publish_job(ctx["db"], content, actor=ctx["owner"])
    cancel_publish_job(ctx["db"], content, reason="material_content_changed", actor=ctx["owner"])
    assert job.status == "cancelled"
    second_content = make_validated_content(ctx)
    second = sync_publish_job(ctx["db"], second_content, actor=ctx["owner"])
    second.status = "simulating_publish"
    cancel_publish_job(
        ctx["db"], second_content, reason="material_content_changed", actor=ctx["owner"]
    )
    assert second.status == "action_required"


def test_worker_rechecks_integration_before_adapter(publishing_context):
    ctx = publishing_context
    job = queue_now(ctx)
    ctx["integration"].integration_status = "revoked"
    ctx["db"].commit()
    worker = InstagramPublishWorker(
        settings=worker_settings(), session_factory=ctx["factory"], worker_id="blocked-worker"
    )
    worker.run_once()
    ctx["db"].expire_all()
    stored = ctx["db"].get(InstagramPublishJob, job.id)
    assert stored.status == "action_required"
    assert stored.provider_media_id is None
    assert ctx["db"].query(AuditLog).filter_by(action="integration_blocked_publish").count() == 1


def test_worker_blocks_validation_revoked_after_scheduling(publishing_context):
    ctx = publishing_context
    job = queue_now(ctx)
    validation = (
        ctx["db"].query(InstagramContentValidation).filter_by(content_id=job.content_item_id).one()
    )
    validation.invalidated_at = utc_now()
    ctx["db"].commit()
    worker = InstagramPublishWorker(
        settings=worker_settings(), session_factory=ctx["factory"], worker_id="revoked-worker"
    )
    worker.run_once()
    ctx["db"].expire_all()
    stored = ctx["db"].get(InstagramPublishJob, job.id)
    assert stored.status == "action_required"
    assert stored.provider_error_code == "publish_validation_revoked"
    assert stored.provider_media_id is None


def test_worker_commits_started_state_before_calling_adapter(publishing_context):
    ctx = publishing_context
    job = queue_now(ctx)

    class InspectingAdapter(SimulatedInstagramPublishingAdapter):
        def publish(self, request):
            with ctx["factory"]() as observer:
                visible = observer.get(InstagramPublishJob, job.id)
                assert visible.status == "simulating_publish"
                assert visible.claimed_by == "transaction-worker"
            return super().publish(request)

    worker = InstagramPublishWorker(
        settings=worker_settings(),
        session_factory=ctx["factory"],
        adapter=InspectingAdapter(),
        worker_id="transaction-worker",
    )
    worker.run_once()
    ctx["db"].expire_all()
    assert ctx["db"].get(InstagramPublishJob, job.id).status == "published"


def test_disabling_service_cancels_pending_and_reenable_does_not_revive(publishing_context):
    ctx = publishing_context
    job = queue_now(ctx)
    settings = ctx["db"].get(InstagramContentSettings, ctx["business"].id)
    settings.enabled = False
    assert (
        cancel_business_jobs(
            ctx["db"], ctx["business"].id, "instagram_content_service_disabled", ctx["owner"]
        )
        == 1
    )
    ctx["db"].commit()
    assert job.status == "cancelled"
    settings.enabled = True
    ctx["db"].commit()
    assert ctx["db"].get(InstagramPublishJob, job.id).status == "cancelled"


def test_owner_and_admin_ui_expose_simulated_job_states_and_authorized_actions():
    root = Path(__file__).resolve().parents[2]
    owner = (root / "autonogrow-owner" / "owner.js").read_text(encoding="utf-8")
    admin = (root / "autonogrow-admin" / "admin.js").read_text(encoding="utf-8")
    for state in ("queued", "simulating_publish", "published", "retry_wait", "action_required"):
        assert state in owner
        assert state in admin
    for owner_action in ("publish-now", "cancel-publish", "retry-publish"):
        assert f'data-owner-instagram-action="{owner_action}"' in owner
    assert "data-owner-instagram-action" not in admin
    assert "solo lectura" in admin
