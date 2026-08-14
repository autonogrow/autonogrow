from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.services.instagram_asset_url_service import (
    SignedAssetURLInvalid,
    resolve_authorized_final_asset,
    verify_signed_asset_request,
)

router = APIRouter(prefix="/api/public/instagram-assets", tags=["instagram-asset-delivery"])


def _resolve(
    business_id: int,
    version_id: int,
    asset_id: int,
    expires: int,
    signature: str,
    db: Session,
):
    try:
        verify_signed_asset_request(
            get_settings(),
            business_id=business_id,
            version_id=version_id,
            asset_id=asset_id,
            expires=expires,
            signature=signature,
        )
        return resolve_authorized_final_asset(
            db, business_id=business_id, version_id=version_id, asset_id=asset_id
        )
    except SignedAssetURLInvalid as exc:
        raise HTTPException(status_code=404, detail="Asset not found") from exc


@router.get("/{business_id}/{version_id}/{asset_id}")
def get_instagram_asset(
    business_id: int,
    version_id: int,
    asset_id: int,
    expires: int = Query(..., gt=0),
    signature: str = Query(..., min_length=64, max_length=64),
    db: Session = Depends(get_db),
):
    resolved = _resolve(business_id, version_id, asset_id, expires, signature, db)
    return FileResponse(
        resolved.path,
        media_type=resolved.media_type,
        headers={"Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff"},
    )


@router.head("/{business_id}/{version_id}/{asset_id}")
def head_instagram_asset(
    business_id: int,
    version_id: int,
    asset_id: int,
    expires: int = Query(..., gt=0),
    signature: str = Query(..., min_length=64, max_length=64),
    db: Session = Depends(get_db),
):
    resolved = _resolve(business_id, version_id, asset_id, expires, signature, db)
    return Response(
        headers={
            "Content-Type": resolved.media_type,
            "Content-Length": str(resolved.size_bytes),
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
        }
    )
