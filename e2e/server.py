from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def install_google_mock(app_env: str) -> None:
    """Replace Google verification only inside the explicitly test-only runner."""
    if app_env != "test":
        raise RuntimeError("The E2E Google mock can only run with APP_ENV=test")

    from google.oauth2 import id_token as google_id_token

    claims_by_token = {
        "e2e-customer": {
            "sub": "google-customer-e2e",
            "email": "customer@e2e.test",
            "email_verified": True,
            "name": "María E2E",
        },
        "e2e-claim": {
            "sub": "google-claim-e2e",
            "email": "claim@e2e.test",
            "email_verified": True,
            "name": "Claim E2E",
        },
        "e2e-admin-a": {
            "sub": "google-admin-a-e2e",
            "email": "admin-a@e2e.test",
            "email_verified": True,
            "name": "Admin Salón E2E",
        },
        "e2e-owner": {
            "sub": "google-owner-e2e",
            "email": "owner@e2e.test",
            "email_verified": True,
            "name": "Owner E2E",
        },
    }

    def verify_e2e_token(token: str, _request: object, audience: str) -> dict[str, object]:
        if audience != os.environ.get("GOOGLE_CLIENT_ID") or token not in claims_by_token:
            raise ValueError("Invalid E2E Google credential")
        return claims_by_token[token]

    google_id_token.verify_oauth2_token = verify_e2e_token


def build_app():
    app_env = os.environ.get("APP_ENV", "")
    install_google_mock(app_env)
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))

    from app.main import app

    app.mount("/autonogrow-admin", StaticFiles(directory=ROOT / "autonogrow-admin", html=True))
    app.mount(
        "/autonogrow-customer", StaticFiles(directory=ROOT / "autonogrow-customer", html=True)
    )
    app.mount("/autonogrow-landing", StaticFiles(directory=ROOT / "autonogrow-landing", html=True))
    app.mount("/autonogrow-owner", StaticFiles(directory=ROOT / "autonogrow-owner", html=True))
    app.mount("/autonogrow-shared", StaticFiles(directory=ROOT / "autonogrow-shared"))
    app.mount("/privacy", StaticFiles(directory=ROOT / "privacy", html=True))
    app.mount("/data-deletion", StaticFiles(directory=ROOT / "data-deletion", html=True))
    return app


app = build_app()
