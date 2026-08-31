from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import Base, get_db
from app.core.security import get_current_user, has_owner_access, require_owner
from app.models import Business, BusinessUser, User
from app.routers.auth import router as auth_router
from app.routers.auth import serialize_user
from app.routers.owner_onboarding import router as owner_onboarding_router

ROOT = Path(__file__).resolve().parents[2]
TARGET_EMAIL = "info.autonogrow@gmail.com"
SENTINEL_EMAIL = "another-owner@example.test"


@pytest.fixture
def db():
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
def owner_allowlist(monkeypatch):
    settings = get_settings()

    def set_allowlist(value: str) -> None:
        monkeypatch.setattr(settings, "owner_allowed_emails", value)

    set_allowlist(SENTINEL_EMAIL)
    return set_allowlist


def user(email: str = TARGET_EMAIL, **values) -> User:
    values.setdefault("is_active", True)
    values.setdefault("is_owner", False)
    return User(email=email, **values)


def test_allowed_active_email_is_effective_owner(owner_allowlist) -> None:
    owner_allowlist(TARGET_EMAIL)
    assert has_owner_access(user()) is True
    assert require_owner(user()).email == TARGET_EMAIL


def test_owner_allowlist_is_case_and_whitespace_insensitive(owner_allowlist) -> None:
    owner_allowlist("  INFO.AUTONOGROW@GMAIL.COM  ")
    assert has_owner_access(user("Info.AutonoGrow@Gmail.Com")) is True


def test_email_outside_allowlist_is_not_owner(owner_allowlist) -> None:
    owner_allowlist(SENTINEL_EMAIL)
    candidate = user(is_owner=True)
    assert has_owner_access(candidate) is False
    with pytest.raises(HTTPException) as denied:
        require_owner(candidate)
    assert denied.value.status_code == 403
    assert candidate.is_owner is False


def test_inactive_user_is_denied_even_when_email_is_allowed(owner_allowlist) -> None:
    owner_allowlist(TARGET_EMAIL)
    candidate = user()
    candidate.is_active = False
    assert has_owner_access(candidate) is False
    with pytest.raises(HTTPException) as denied:
        require_owner(candidate)
    assert denied.value.status_code == 403


def test_existing_user_added_to_allowlist_needs_no_recreation(db, owner_allowlist) -> None:
    candidate = user()
    db.add(candidate)
    db.commit()
    existing_id = candidate.id

    owner_allowlist(TARGET_EMAIL)

    assert serialize_user(db, candidate)["is_owner"] is True
    assert db.query(User).filter(User.email == TARGET_EMAIL).count() == 1
    assert candidate.id == existing_id


def test_removed_email_loses_owner_without_another_login(db, owner_allowlist) -> None:
    candidate = user(is_owner=True)
    db.add(candidate)
    db.commit()
    owner_allowlist(TARGET_EMAIL)
    assert require_owner(candidate) is candidate

    owner_allowlist(SENTINEL_EMAIL)

    assert serialize_user(db, candidate)["is_owner"] is False
    with pytest.raises(HTTPException) as denied:
        require_owner(candidate)
    assert denied.value.status_code == 403


@pytest.fixture
def access_client(db, owner_allowlist):
    owner_allowlist(TARGET_EMAIL)
    owner = user()
    normal = user("normal@example.test")
    admin_user = user("admin@example.test")
    business = Business(name="Existing business", slug="existing-business", status="active")
    db.add_all([owner, normal, admin_user, business])
    db.flush()
    db.add(
        BusinessUser(
            business_id=business.id,
            user_id=admin_user.id,
            role="business_admin",
            active=True,
        )
    )
    db.commit()

    current = {"user": normal}
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(owner_onboarding_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    with TestClient(app) as client:
        yield client, current, owner, normal, admin_user


def onboarding_payload(slug: str) -> dict:
    return {
        "name": f"Controlled {slug}",
        "slug": slug,
        "modules": ["essential", "growth", "social"],
    }


def test_normal_user_cannot_post_owner_onboarding(access_client) -> None:
    client, current, _owner, normal, _admin = access_client
    current["user"] = normal
    response = client.post(
        "/api/owner/businesses/onboarding", json=onboarding_payload("normal-denied")
    )
    assert response.status_code == 403


def test_business_admin_cannot_post_owner_onboarding(access_client) -> None:
    client, current, _owner, _normal, admin = access_client
    current["user"] = admin
    response = client.post(
        "/api/owner/businesses/onboarding", json=onboarding_payload("admin-denied")
    )
    assert response.status_code == 403


def test_effective_owner_can_post_owner_onboarding(access_client) -> None:
    client, current, owner, _normal, _admin = access_client
    current["user"] = owner
    response = client.post(
        "/api/owner/businesses/onboarding", json=onboarding_payload("owner-allowed")
    )
    assert response.status_code == 201
    assert response.json()["business"]["slug"] == "owner-allowed"


def test_auth_me_reports_effective_owner(access_client) -> None:
    client, current, owner, _normal, _admin = access_client
    assert owner.is_owner is False
    current["user"] = owner
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["is_owner"] is True
    assert response.json()["can_access_owner"] is True


def test_owner_frontend_revalidates_identity_before_gating_on_403() -> None:
    source = (ROOT / "autonogrow-owner" / "owner.js").read_text(encoding="utf-8")
    assert "async function revalidateOwnerAfterForbidden()" in source
    assert "const current = await AutonoGrowAuth.getMe();" in source
    assert "if (!current?.is_owner)" in source
    assert (
        'if (response.status === 403) queueMicrotask(() => revalidateOwnerAfterForbidden());'
        in source
    )
    assert (
        'if (response.status === 403) queueMicrotask(() => showOwnerLogin('
        not in source
    )
