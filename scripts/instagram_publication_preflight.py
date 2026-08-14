"""Read-only Meta/Instagram publication preflight for one staging content item."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models import InstagramContent  # noqa: E402
from app.services.instagram_asset_url_service import (  # noqa: E402
    SignedAssetURLInvalid,
    build_signed_asset_url,
)
from app.services.instagram_publish_service import (  # noqa: E402
    _active_validation,
    _current_version,
    publication_preflight,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-id", type=int, required=True)
    parser.add_argument("--business-id", type=int, required=True)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    payload: dict[str, object] = {
        "ok": False,
        "app_env": settings.app_env,
        "provider_mode": settings.instagram_publishing_mode,
        "content_id": args.content_id,
        "business_id": args.business_id,
    }
    with SessionLocal() as db:
        content = (
            db.query(InstagramContent)
            .filter(
                InstagramContent.id == args.content_id,
                InstagramContent.business_id == args.business_id,
            )
            .first()
        )
        if content is None:
            payload["code"] = "content_not_found"
        else:
            version = _current_version(db, content)
            preflight = publication_preflight(
                db,
                content,
                version=version,
                settings=settings,
                validate_files=True,
            )
            integration = preflight.integration
            version_approved = bool(
                version and _active_validation(db, content, version.id) is not None
            )
            payload.update(
                {
                    "ok": preflight.ok,
                    "publishing_available": preflight.ok,
                    "code": preflight.code,
                    "content_status": content.status,
                    "version": version.version_number if version else None,
                    "version_approved": version_approved,
                    "format": version.format if version else None,
                    "format_supported": bool(
                        version
                        and (
                            settings.instagram_publishing_mode != "meta"
                            or version.format == "single_image"
                        )
                    ),
                    "asset_count": len(version.asset_links) if version else 0,
                    "integration_status": (
                        integration.integration_status if integration else "missing"
                    ),
                    "integration_health": integration.health_status if integration else "missing",
                    "professional_account_present": bool(
                        integration and integration.external_account_id.strip()
                    ),
                    "encrypted_token_present": bool(
                        integration
                        and integration.encrypted_access_token
                        and integration.encryption_key_version
                    ),
                }
            )
            signed_url_ready = False
            signed_url_host = None
            if version and version.asset_links:
                try:
                    signed_url = build_signed_asset_url(
                        settings,
                        business_id=content.business_id,
                        version_id=version.id,
                        asset_id=version.asset_links[0].asset_id,
                    )
                    signed_url_ready = True
                    signed_url_host = urlsplit(signed_url).hostname
                except SignedAssetURLInvalid:
                    pass
            payload["signed_url_ready"] = signed_url_ready
            payload["signed_url_host"] = signed_url_host
    output = json.dumps(payload, indent=2 if args.json else None, sort_keys=True)
    print(output)
    return 0 if payload["ok"] and payload.get("signed_url_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
