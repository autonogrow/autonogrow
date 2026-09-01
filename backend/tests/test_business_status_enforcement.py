from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.database import Base
from app.core.security import (
    require_business_access,
    require_business_admin,
    require_business_operational_status,
    require_business_operational_status_by_id,
)
from app.models import Business, BusinessUser, Conversation, User
from app.services.conversation_automation_service import process_inbound_automation
from app.services.conversation_service import add_message

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def status_context():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    admin = User(email="status-admin@test.local")
    staff = User(email="status-staff@test.local")
    owner = User(email="status-owner@test.local", is_owner=True)
    businesses = {
        status: Business(slug=f"status-{status}", name=status, status=status)
        for status in (
            "draft",
            "onboarding",
            "configuration_pending",
            "ready",
            "active",
            "suspended",
            "archived",
        )
    }
    db.add_all([admin, staff, owner, *businesses.values()])
    db.flush()
    for business in businesses.values():
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
            ]
        )
    db.commit()
    yield db, businesses, admin, staff, owner
    db.close()
    engine.dispose()


def request(method: str) -> Request:
    return Request({"type": "http", "method": method, "path": "/", "headers": []})


@pytest.mark.parametrize(
    "status",
    ("draft", "onboarding", "configuration_pending", "ready", "suspended", "archived"),
)
def test_every_non_active_status_rejects_operational_mutations(status_context, status):
    db, businesses, *_ = status_context
    with pytest.raises(HTTPException) as denied:
        require_business_operational_status(businesses[status].slug, request("POST"), db)
    assert denied.value.status_code == 403
    assert denied.value.detail == {
        "code": "business_not_operational",
        "message": "Este negocio no está activo. Las operaciones están temporalmente deshabilitadas.",
        "business_status": status,
    }


@pytest.mark.parametrize("status", ("active", "suspended"))
def test_historical_reads_preserve_membership_and_role_contract(status_context, status):
    db, businesses, admin, staff, _owner = status_context
    business = businesses[status]
    assert require_business_operational_status(business.slug, request("GET"), db) is None
    assert require_business_access(business.slug, staff, db) is staff
    assert require_business_admin(business.slug, admin, db) is admin


def test_archived_business_is_owner_only_even_for_reads(status_context):
    db, businesses, admin, staff, owner = status_context
    archived = businesses["archived"]
    assert require_business_access(archived.slug, owner, db) is owner
    for actor, guard in ((staff, require_business_access), (admin, require_business_admin)):
        with pytest.raises(HTTPException) as denied:
            guard(archived.slug, actor, db)
        assert denied.value.detail["business_status"] == "archived"


def test_active_business_keeps_existing_admin_and_staff_operations(status_context):
    db, businesses, admin, staff, _owner = status_context
    active = businesses["active"]
    assert require_business_operational_status(active.slug, request("PATCH"), db) is None
    assert require_business_access(active.slug, staff, db) is staff
    assert require_business_admin(active.slug, admin, db) is admin


@pytest.mark.parametrize("status", ("suspended", "archived"))
def test_owner_operational_routes_do_not_bypass_business_status(status_context, status):
    db, businesses, *_ = status_context
    business = businesses[status]
    assert require_business_operational_status_by_id(business.id, request("GET"), db) is None
    with pytest.raises(HTTPException) as denied:
        require_business_operational_status_by_id(business.id, request("POST"), db)
    assert denied.value.detail["code"] == "business_not_operational"


@pytest.mark.parametrize("status", ("suspended", "archived"))
def test_inbound_is_retained_but_automation_creates_no_outbound(status_context, status):
    db, businesses, *_ = status_context
    business = businesses[status]
    conversation = Conversation(
        business_id=business.id,
        channel="manual",
        external_user_id=f"customer-{status}",
        status="pending",
    )
    db.add(conversation)
    db.flush()
    inbound = add_message(
        db,
        conversation=conversation,
        direction="inbound",
        sender_type="customer",
        body="Quiero reservar",
    )
    result = process_inbound_automation(
        db,
        business=business,
        conversation=conversation,
        message=inbound,
    )
    db.flush()
    assert result["status"] == "skipped"
    assert result["reason"] == "business_not_operational"
    assert len(conversation.messages) == 1


def test_admin_frontend_distinguishes_operational_403_from_access_denial():
    html = (ROOT / "autonogrow-admin" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "autonogrow-admin" / "styles.css").read_text(encoding="utf-8")
    js = (ROOT / "autonogrow-admin" / "admin.js").read_text(encoding="utf-8")
    assert 'id="business-operational-banner"' in html
    assert "business_not_operational" in js
    assert "lastBusinessOperationalStatus" in js
    assert "applyOperationalBusinessState" in js
    assert "business-non-operational" in css
