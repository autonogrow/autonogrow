from __future__ import annotations

from base64 import urlsafe_b64decode
from datetime import datetime, timedelta
from pathlib import Path
from secrets import token_urlsafe
from unittest.mock import patch

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import Base, get_db
from app.core.migration_state import alembic_config
from app.core.security import SESSION_COOKIE, create_session_token, read_session_token
from app.middleware.csrf import CSRFMiddleware
from app.models import AuditLog, AuthSession, Business, BusinessUser, User
from app.routers.auth import router as auth_router
from app.services.auth_session_service import session_token_hash

ROOT = Path(__file__).resolve().parents[2]


def decode_urlsafe_segment(value: str) -> bytes:
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))


@pytest.fixture
def auth_context(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "google_client_id", "session-tests.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "session_secret", "session-tests-secret-with-at-least-32-characters")
    monkeypatch.setattr(settings, "cookie_secure", False)
    monkeypatch.setattr(settings, "csrf_enabled", True)
    monkeypatch.setattr(settings, "owner_allowed_emails", "owner@sessions.test")

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)
    app.include_router(auth_router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db

    claims = {
        "user-a": {
            "sub": "google-user-a",
            "email": "user-a@sessions.test",
            "email_verified": True,
            "name": "User A",
        },
        "user-b": {
            "sub": "google-user-b",
            "email": "user-b@sessions.test",
            "email_verified": True,
            "name": "User B",
        },
        "owner": {
            "sub": "google-owner",
            "email": "owner@sessions.test",
            "email_verified": True,
            "name": "Owner",
        },
    }

    def verify(token, _request, audience):
        assert audience == settings.google_client_id
        if token not in claims:
            raise ValueError("unknown test credential")
        return claims[token]

    with (
        patch("google.oauth2.id_token.verify_oauth2_token", side_effect=verify),
        TestClient(app) as client_a,
        TestClient(app) as client_b,
        TestClient(app) as client_c,
    ):
        yield {
            "db": db,
            "settings": settings,
            "clients": (client_a, client_b, client_c),
            "claims": claims,
        }
    db.close()
    engine.dispose()


def login(client: TestClient, credential: str = "user-a"):
    response = client.post("/api/auth/google", json={"credential": credential})
    assert response.status_code == 200, response.text
    return response


def csrf_headers(client: TestClient) -> dict[str, str]:
    response = client.get("/api/auth/csrf")
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_login_creates_opaque_server_session_and_legacy_or_unknown_tokens_fail_closed(
    auth_context,
):
    db = auth_context["db"]
    client_a, client_b, client_c = auth_context["clients"]
    response = login(client_a)
    cookie = client_a.cookies.get(SESSION_COOKIE)
    assert cookie
    raw_token = read_session_token(cookie)
    assert raw_token and len(raw_token) >= 64
    row = db.query(AuthSession).one()
    assert row.user_id == response.json()["user"]["id"]
    assert row.token_hash == session_token_hash(raw_token)
    assert raw_token != row.token_hash
    assert row.expires_at - row.created_at == timedelta(days=7)
    assert client_a.get("/api/auth/me").status_code == 200

    second_cookie = login(client_b).cookies.get(SESSION_COOKIE)
    assert second_cookie != cookie
    assert read_session_token(second_cookie) != raw_token

    unknown_cookie = create_session_token(token_urlsafe(48))
    client_b.cookies.set(SESSION_COOKIE, unknown_cookie, domain="testserver.local", path="/")
    assert client_b.get("/api/auth/me").status_code == 401

    legacy_cookie = URLSafeTimedSerializer(
        auth_context["settings"].session_secret,
        salt="autonogrow-session-v1",
    ).dumps({"user_id": row.user_id})
    client_b.cookies.set(SESSION_COOKIE, legacy_cookie, domain="testserver.local", path="/")
    assert client_b.get("/api/auth/me").status_code == 401
    recovered_cookie = login(client_b).cookies.get(SESSION_COOKIE)
    assert recovered_cookie not in {legacy_cookie, unknown_cookie, cookie}
    assert client_b.get("/api/auth/me").status_code == 200

    login(client_c, "user-b")
    signed_value, signature = cookie.rsplit(".", maxsplit=1)
    replacement = "A" if signature[0] != "A" else "B"
    tampered_signature = f"{replacement}{signature[1:]}"
    assert decode_urlsafe_segment(tampered_signature) != decode_urlsafe_segment(signature)
    tampered_cookie = f"{signed_value}.{tampered_signature}"
    client_c.cookies.set(
        SESSION_COOKIE, tampered_cookie, domain="testserver.local", path="/"
    )
    assert client_c.get("/api/auth/me").status_code == 401
    client_c.cookies.set(SESSION_COOKIE, cookie, domain="testserver.local", path="/")
    assert client_c.get("/api/auth/me").status_code == 200

    audits = db.query(AuditLog).filter(AuditLog.action == "session_created").all()
    assert len(audits) == 4
    assert all(item.resource_type == "auth_session" for item in audits)
    assert raw_token not in " ".join(
        str(value)
        for item in audits
        for value in (item.resource_id, item.metadata_json, item.actor_email)
    )


def test_logout_revokes_copied_cookie_and_is_idempotent_for_every_invalid_state(auth_context):
    db = auth_context["db"]
    client, _client_b, _client_c = auth_context["clients"]
    login(client)
    copied_cookie = client.cookies.get(SESSION_COOKIE)
    csrf_headers(client)

    first = client.post("/api/auth/logout")
    assert first.status_code == 200
    row = db.query(AuthSession).one()
    assert row.revoked_at is not None
    assert client.cookies.get(SESSION_COOKIE) is None

    client.cookies.set(SESSION_COOKIE, copied_cookie, domain="testserver.local", path="/")
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/logout").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200

    client.cookies.set(SESSION_COOKIE, "corrupt-cookie", domain="testserver.local", path="/")
    assert client.post("/api/auth/logout").status_code == 200
    assert client.cookies.get(SESSION_COOKIE) is None
    assert db.query(AuditLog).filter(AuditLog.action == "session_revoked").count() == 1


def test_http_login_logout_relogin_and_multi_device_logout_all(auth_context):
    db = auth_context["db"]
    client_a, client_b, client_c = auth_context["clients"]
    login(client_a)
    cookie_a = client_a.cookies.get(SESSION_COOKIE)
    login(client_b)
    cookie_b = client_b.cookies.get(SESSION_COOKIE)
    assert cookie_a != cookie_b

    assert client_a.post("/api/auth/logout").status_code == 200
    client_a.cookies.set(SESSION_COOKIE, cookie_a)
    assert client_a.get("/api/auth/me").status_code == 401
    assert client_b.get("/api/auth/me").status_code == 200

    login(client_a)
    headers = csrf_headers(client_b)
    logout_all = client_b.post("/api/auth/logout-all", headers=headers)
    assert logout_all.status_code == 200
    assert logout_all.json()["revoked_sessions"] == 2
    assert client_a.get("/api/auth/me").status_code == 401
    assert client_b.get("/api/auth/me").status_code == 401

    assert login(client_c).status_code == 200
    assert client_c.get("/api/auth/me").status_code == 200
    assert db.query(AuditLog).filter(AuditLog.action == "all_sessions_revoked").count() == 1


def test_expired_session_is_permanently_revoked_and_inactive_user_keeps_403_contract(
    auth_context,
):
    db = auth_context["db"]
    client, _client_b, _client_c = auth_context["clients"]
    login(client)
    row = db.query(AuthSession).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()

    assert client.get("/api/auth/me").status_code == 401
    db.refresh(row)
    assert row.revoked_at is not None
    row.expires_at = datetime.utcnow() + timedelta(days=7)
    db.commit()
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/logout").status_code == 200

    login(client)
    user = db.query(User).filter(User.email == "user-a@sessions.test").one()
    user.is_active = False
    db.commit()
    assert client.get("/api/auth/me").status_code == 403
    assert client.post("/api/auth/logout").status_code == 200


def test_membership_and_owner_changes_take_effect_without_over_revoking_session(auth_context):
    db = auth_context["db"]
    client, owner_client, _client_c = auth_context["clients"]
    user = User(
        email="user-a@sessions.test",
        google_sub="google-user-a",
        is_active=True,
        email_verified=True,
    )
    owner = User(
        email="owner@sessions.test",
        google_sub="google-owner",
        is_active=True,
        email_verified=True,
    )
    first = Business(name="First", slug="session-first", status="active")
    second = Business(name="Second", slug="session-second", status="active")
    db.add_all((user, owner, first, second))
    db.flush()
    first_membership = BusinessUser(
        business_id=first.id, user_id=user.id, role="business_admin", active=True
    )
    second_membership = BusinessUser(
        business_id=second.id, user_id=user.id, role="business_staff", active=True
    )
    db.add_all((first_membership, second_membership))
    db.commit()

    login(client)
    assert {item["slug"] for item in client.get("/api/auth/me").json()["businesses"]} == {
        first.slug,
        second.slug,
    }
    first_membership.active = False
    db.commit()
    current = client.get("/api/auth/me")
    assert current.status_code == 200
    assert [item["slug"] for item in current.json()["businesses"]] == [second.slug]
    assert current.json()["can_access_customer_portal"] is True
    assert db.query(AuthSession).filter(AuthSession.user_id == user.id).one().revoked_at is None

    login(owner_client, "owner")
    assert owner_client.get("/api/auth/me").json()["is_owner"] is True
    auth_context["settings"].owner_allowed_emails = "someone-else@sessions.test"
    removed = owner_client.get("/api/auth/me")
    assert removed.status_code == 200
    assert removed.json()["is_owner"] is False
    assert db.query(AuthSession).filter(AuthSession.user_id == owner.id).one().revoked_at is None


def test_owner_security_endpoint_revokes_target_but_business_user_cannot(auth_context):
    db = auth_context["db"]
    target_a, target_b, owner_client = auth_context["clients"]
    login(target_a)
    target_id = target_a.get("/api/auth/me").json()["id"]
    login(target_b)
    login(owner_client, "owner")

    denied = target_a.post(
        f"/api/auth/users/{target_id}/sessions/revoke-all",
        headers=csrf_headers(target_a),
    )
    assert denied.status_code == 403

    revoked = owner_client.post(
        f"/api/auth/users/{target_id}/sessions/revoke-all",
        headers=csrf_headers(owner_client),
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_sessions"] == 2
    assert target_a.get("/api/auth/me").status_code == 401
    assert target_b.get("/api/auth/me").status_code == 401
    assert owner_client.get("/api/auth/me").status_code == 200
    audit = db.query(AuditLog).filter(AuditLog.action == "all_sessions_revoked").one()
    assert audit.resource_id == str(target_id)
    assert "revoked_by_owner" in (audit.metadata_json or "")


def test_auth_session_migration_upgrade_and_downgrade(tmp_path):
    path = tmp_path / "auth-sessions.db"
    config = alembic_config()
    config.attributes["database_url"] = f"sqlite:///{path.as_posix()}"
    command.upgrade(config, "20260901_29")
    engine = create_engine(config.attributes["database_url"])
    assert "auth_sessions" not in inspect(engine).get_table_names()
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(config.attributes["database_url"])
    inspector = inspect(engine)
    assert {
        "id",
        "user_id",
        "token_hash",
        "created_at",
        "expires_at",
        "revoked_at",
    } == {item["name"] for item in inspector.get_columns("auth_sessions")}
    assert {"ix_auth_sessions_user_revoked", "ix_auth_sessions_expires_at"} <= {
        item["name"] for item in inspector.get_indexes("auth_sessions")
    }
    assert any(
        item["referred_table"] == "users" and item["constrained_columns"] == ["user_id"]
        for item in inspector.get_foreign_keys("auth_sessions")
    )
    engine.dispose()

    command.downgrade(config, "20260901_29")
    engine = create_engine(config.attributes["database_url"])
    assert "auth_sessions" not in inspect(engine).get_table_names()
    engine.dispose()


def test_frontends_clear_auth_state_on_401_keep_403_distinct_and_logout_robustly():
    shared = (ROOT / "autonogrow-shared" / "auth.js").read_text(encoding="utf-8")
    owner = (ROOT / "autonogrow-owner" / "owner.js").read_text(encoding="utf-8")
    admin = (ROOT / "autonogrow-admin" / "admin.js").read_text(encoding="utf-8")
    customer = (ROOT / "autonogrow-customer" / "customer.js").read_text(encoding="utf-8")
    landing = (ROOT / "autonogrow-landing" / "script.js").read_text(encoding="utf-8")

    assert 'response.status === 401' in shared
    assert 'new CustomEvent("autonogrow:auth-invalidated")' in shared
    assert 'catch (_) { /* Local cleanup must remain available' in shared
    assert '["/api/auth/google", "/api/auth/logout"].includes(path)' in shared
    assert 'if (response.status === 401) queueMicrotask(() => showOwnerLogin());' in owner
    assert 'if (response.status === 403) queueMicrotask(() => revalidateOwnerAfterForbidden());' in owner
    assert 'if (businessResponse.status === 401) return showAdminLogin();' in admin
    assert 'businessResponse.status === 403 && lastBusinessOperationalStatus' in admin
    assert 'if (response.status === 401) queueMicrotask(() => showCustomerLogin(true));' in customer
    assert 'if (status === 403) return "No tienes permiso' in customer
    assert 'userLabel.textContent = "Reserva sin iniciar sesión disponible"' in landing
