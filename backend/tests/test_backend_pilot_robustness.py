from __future__ import annotations

import os
from asyncio import run
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from threading import Barrier

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import Headers
from starlette.requests import Request

from app.core.database import Base, get_db
from app.core.security import require_owner
from app.middleware.rate_limit import RateLimitMiddleware
from app.models import (
    Booking,
    BookingAttachment,
    Business,
    BusinessGalleryImage,
    Conversation,
    ConversationAutomationRule,
    ConversationAutomationSettings,
    ConversationMessage,
    ConversationTemplate,
    Customer,
    CustomerAccountLink,
    InstagramContent,
    InstagramFinalAsset,
    InstagramRawAsset,
    User,
)
from app.routers.attachments import upload_booking_attachments
from app.routers.owner import list_owner_businesses
from app.routers.owner import router as owner_router
from app.services.conversation_automation_service import ensure_automation_configuration
from app.services.conversation_service import serialize_conversation_list
from app.services.customer_identity_service import link_customer_account
from app.services.storage_reconciliation_service import reconcile_managed_storage


def memory_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def test_owner_business_list_has_bounded_queries_and_server_limit() -> None:
    engine, db = memory_session()
    try:
        db.add_all(
            [Business(slug=f"pilot-{index}", name=f"Pilot {index}") for index in range(20)]
        )
        db.commit()
        query_count = 0

        def count_query(*_args) -> None:
            nonlocal query_count
            query_count += 1

        event.listen(engine, "before_cursor_execute", count_query)
        one = list_owner_businesses(limit=1, offset=0, db=db)
        one_count = query_count
        query_count = 0
        twenty = list_owner_businesses(limit=20, offset=0, db=db)
        twenty_count = query_count
        event.remove(engine, "before_cursor_execute", count_query)

        assert len(one) == 1
        assert len(twenty) == 20
        assert one_count <= 8
        assert twenty_count <= 8
        assert twenty_count - one_count <= 1

        app = FastAPI()
        app.include_router(owner_router)
        app.dependency_overrides[require_owner] = lambda: None
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            assert client.get("/api/owner/businesses?limit=201").status_code == 422
            assert len(client.get("/api/owner/businesses?limit=3").json()) == 3
    finally:
        db.close()
        engine.dispose()


def test_conversation_preview_queries_do_not_grow_per_row() -> None:
    engine, db = memory_session()
    try:
        business = Business(slug="conversation-pilot", name="Conversation pilot")
        db.add(business)
        db.flush()
        conversations = [
            Conversation(
                business_id=business.id,
                channel="instagram",
                external_user_id=f"customer-{index}",
            )
            for index in range(20)
        ]
        db.add_all(conversations)
        db.commit()
        conversations = db.query(Conversation).order_by(Conversation.id).all()
        query_count = 0

        def count_query(*_args) -> None:
            nonlocal query_count
            query_count += 1

        event.listen(engine, "before_cursor_execute", count_query)
        serialize_conversation_list(db, conversations[:1])
        one_count = query_count
        query_count = 0
        payload = serialize_conversation_list(db, conversations)
        twenty_count = query_count
        event.remove(engine, "before_cursor_execute", count_query)

        assert len(payload) == 20
        assert one_count <= 5
        assert twenty_count <= 5
        assert twenty_count - one_count <= 1
    finally:
        db.close()
        engine.dispose()


def test_conversation_preview_preserves_out_of_order_whatsapp_window() -> None:
    engine, db = memory_session()
    now = datetime.now(timezone.utc)
    try:
        business = Business(slug="whatsapp-window-pilot", name="WhatsApp window pilot")
        conversation = Conversation(
            business=business,
            channel="whatsapp",
            external_user_id="34600000000",
            customer_phone="34600000000",
        )
        db.add_all([business, conversation])
        db.flush()
        db.add_all(
            [
                ConversationMessage(
                    conversation_id=conversation.id,
                    direction="inbound",
                    sender_type="customer",
                    body="Recent provider event",
                    provider_message_id="wamid-recent",
                    raw_payload_json=f'{{"timestamp":"{int((now - timedelta(hours=1)).timestamp())}"}}',
                    created_at=(now - timedelta(minutes=2)).replace(tzinfo=None),
                ),
                ConversationMessage(
                    conversation_id=conversation.id,
                    direction="inbound",
                    sender_type="customer",
                    body="Delayed old provider event",
                    provider_message_id="wamid-delayed",
                    raw_payload_json=f'{{"timestamp":"{int((now - timedelta(hours=30)).timestamp())}"}}',
                    created_at=(now - timedelta(minutes=1)).replace(tzinfo=None),
                ),
            ]
        )
        db.commit()
        conversation = db.get(Conversation, conversation.id)
        assert conversation is not None

        payload = serialize_conversation_list(db, [conversation])[0]

        assert payload["customer_service_window_open"] is True
    finally:
        db.close()
        engine.dispose()


def test_default_automation_initialization_is_concurrent_and_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "concurrent-defaults.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        business = Business(slug="concurrent-pilot", name="Concurrent pilot")
        db.add(business)
        db.commit()
        business_id = business.id

    barrier = Barrier(2)

    def initialize() -> tuple[int, int]:
        with sessions() as db:
            business = db.get(Business, business_id)
            assert business is not None
            barrier.wait(timeout=5)
            settings, rules = ensure_automation_configuration(db, business)
            db.commit()
            return settings.id, len(rules)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: initialize(), range(2)))

    with sessions() as db:
        assert len({settings_id for settings_id, _ in results}) == 1
        assert {rule_count for _, rule_count in results} == {10}
        assert db.query(ConversationTemplate).filter_by(business_id=business_id).count() == 8
        assert db.query(ConversationAutomationSettings).filter_by(business_id=business_id).count() == 1
        assert db.query(ConversationAutomationRule).filter_by(business_id=business_id).count() == 10
    engine.dispose()


def test_customer_link_race_becomes_business_conflict(tmp_path: Path) -> None:
    database = tmp_path / "concurrent-customer-link.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        business = Business(slug="identity-pilot", name="Identity pilot")
        customer = Customer(business=business, name="Customer", phone="600000003")
        users = [User(email=f"claim-{index}@example.test") for index in range(2)]
        db.add_all([business, customer, *users])
        db.commit()
        customer_id = customer.id
        user_ids = [user.id for user in users]

    barrier = Barrier(2)

    def claim(user_id: int) -> str:
        with sessions() as db:
            user = db.get(User, user_id)
            customer = db.get(Customer, customer_id)
            assert user is not None and customer is not None
            barrier.wait(timeout=5)
            try:
                link_customer_account(db, user=user, customer=customer, method="concurrent_claim")
                db.commit()
                return "linked"
            except ValueError:
                db.rollback()
                return "identity_conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(claim, user_ids))

    assert sorted(outcomes) == ["identity_conflict", "linked"]
    with sessions() as db:
        assert db.query(CustomerAccountLink).filter_by(customer_id=customer_id).count() == 1
    engine.dispose()


def test_rate_limit_buckets_expire_and_stay_bounded() -> None:
    original_max = RateLimitMiddleware.max_buckets
    original_cleanup = RateLimitMiddleware.last_cleanup_at
    try:
        RateLimitMiddleware.buckets.clear()
        RateLimitMiddleware.max_buckets = 3
        RateLimitMiddleware.buckets.update(
            {
                ("expired", "auth"): deque([1.0]),
                ("old", "auth"): deque([80.0]),
                ("middle", "auth"): deque([90.0]),
                ("new", "auth"): deque([99.0]),
            }
        )
        RateLimitMiddleware.prune_buckets(100.0)
        assert ("expired", "auth") not in RateLimitMiddleware.buckets
        assert len(RateLimitMiddleware.buckets) <= RateLimitMiddleware.max_buckets - 1
        assert ("new", "auth") in RateLimitMiddleware.buckets
    finally:
        RateLimitMiddleware.buckets.clear()
        RateLimitMiddleware.max_buckets = original_max
        RateLimitMiddleware.last_cleanup_at = original_cleanup


def test_storage_reconciliation_is_dry_run_safe_and_reports_missing(
    tmp_path: Path,
) -> None:
    engine, db = memory_session()
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    try:
        business = Business(
            slug="storage-pilot",
            name="Storage pilot",
            logo_url="/uploads/businesses/storage-pilot/logo/logo.png",
        )
        customer = Customer(business=business, name="Customer", phone="600000001")
        booking = Booking(
            business=business,
            customer=customer,
            service_name="Service",
            preferred_time="10:00",
        )
        content = InstagramContent(business=business, title="Pilot content", status="draft")
        db.add_all([business, customer, booking, content])
        db.flush()
        raw = InstagramRawAsset(
            business_id=business.id,
            original_filename="raw.png",
            storage_key=f"_instagram_content/{business.id}/raw/raw.png",
            media_type="image/png",
            size_bytes=3,
        )
        invalid = InstagramRawAsset(
            business_id=business.id,
            original_filename="invalid.png",
            storage_key="../outside.png",
            media_type="image/png",
            size_bytes=3,
        )
        final = InstagramFinalAsset(
            business_id=business.id,
            content_id=content.id,
            original_filename="missing.png",
            storage_key=f"_instagram_content/{business.id}/final/{content.id}/missing.png",
            media_type="image/png",
            size_bytes=3,
        )
        gallery = BusinessGalleryImage(
            business_id=business.id,
            url="/uploads/businesses/storage-pilot/gallery/gallery.png",
        )
        attachment = BookingAttachment(
            business_id=business.id,
            booking_id=booking.id,
            original_filename="attachment.png",
            stored_filename="attachment.png",
            file_path="legacy-value-is-not-trusted",
            content_type="image/png",
            size_bytes=3,
        )
        db.add_all([raw, invalid, final, gallery, attachment])
        db.commit()

        referenced_files = (
            tmp_path / raw.storage_key,
            tmp_path / "businesses/storage-pilot/logo/logo.png",
            tmp_path / "businesses/storage-pilot/gallery/gallery.png",
            tmp_path / f"storage-pilot/{booking.id}/attachment.png",
        )
        for path in referenced_files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"img")
        old_orphan = tmp_path / f"_instagram_content/{business.id}/raw/orphan-old.png"
        recent_orphan = tmp_path / f"_instagram_content/{business.id}/raw/orphan-new.png"
        old_orphan.write_bytes(b"old")
        recent_orphan.write_bytes(b"new")
        old_timestamp = (now - timedelta(days=2)).timestamp()
        os.utime(old_orphan, (old_timestamp, old_timestamp))

        report = reconcile_managed_storage(db, root=tmp_path, now=now)
        assert report["dry_run"] is True
        assert old_orphan.relative_to(tmp_path).as_posix() in report["cleanup_candidates"]
        assert recent_orphan.relative_to(tmp_path).as_posix() in report["orphan_files"]
        assert recent_orphan.relative_to(tmp_path).as_posix() not in report["cleanup_candidates"]
        assert final.storage_key in report["missing_files"]
        assert report["invalid_database_paths"][0]["path"] == "../outside.png"
        assert old_orphan.is_file()

        applied = reconcile_managed_storage(db, root=tmp_path, now=now, apply=True)
        assert applied["dry_run"] is False
        assert applied["deleted_files"] == [old_orphan.relative_to(tmp_path).as_posix()]
        assert not old_orphan.exists()
        assert recent_orphan.is_file()
        assert all(path.is_file() for path in referenced_files)
    finally:
        db.close()
        engine.dispose()


def test_attachment_batch_validates_before_writing_files(tmp_path: Path, monkeypatch) -> None:
    engine, db = memory_session()
    try:
        owner = User(email="owner@uploads.test", is_owner=True)
        business = Business(slug="upload-pilot", name="Upload pilot")
        customer = Customer(business=business, name="Customer", phone="600000002")
        booking = Booking(
            business=business,
            customer=customer,
            service_name="Service",
            preferred_time="10:00",
        )
        db.add_all([owner, business, customer, booking])
        db.commit()
        monkeypatch.setattr("app.routers.attachments.get_uploads_dir", lambda: tmp_path)
        files = [
            UploadFile(
                file=BytesIO(b"\x89PNG\r\n\x1a\nvalid"),
                filename="valid.png",
                headers=Headers({"content-type": "image/png"}),
            ),
            UploadFile(
                file=BytesIO(b"not-an-image"),
                filename="invalid.png",
                headers=Headers({"content-type": "image/png"}),
            ),
        ]
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": f"/api/businesses/{business.slug}/bookings/{booking.id}/attachments",
                "headers": [],
                "client": ("test", 50000),
            }
        )
        try:
            run(
                upload_booking_attachments(
                    business.slug,
                    booking.id,
                    request,
                    files,
                    db=db,
                    current_user=owner,
                    booking_token=None,
                )
            )
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("Invalid second image must reject the complete batch")

        assert db.query(BookingAttachment).count() == 0
        assert not list(tmp_path.rglob("*"))
    finally:
        db.close()
        engine.dispose()
