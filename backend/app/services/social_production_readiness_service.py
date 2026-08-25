from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import BusinessGalleryImage, InstagramRawAsset, SocialContentProposal


def production_readiness(
    db: Session, *, business_id: int, proposal: SocialContentProposal
) -> dict[str, object]:
    """Describe production inputs without changing or ranking the opportunity."""
    gallery_images = (
        db.query(BusinessGalleryImage)
        .filter(
            BusinessGalleryImage.business_id == business_id,
            BusinessGalleryImage.active.is_(True),
        )
        .count()
    )
    raws = (
        db.query(InstagramRawAsset)
        .filter(
            InstagramRawAsset.business_id == business_id,
            InstagramRawAsset.active.is_(True),
        )
        .all()
    )
    raw_images = sum(item.media_type.startswith("image/") for item in raws)
    raw_videos = sum(item.media_type == "video/mp4" for item in raws)
    instagram_materialized = sum(item.source_kind == "instagram" for item in raws)
    images = gallery_images + raw_images
    total = images + raw_videos
    try:
        formats = set(json.loads(proposal.recommended_formats_json))
    except (TypeError, json.JSONDecodeError):
        formats = set()
    compatible = bool(images and formats & {"story", "carousel", "static_post"}) or bool(
        raw_videos and "reel" in formats
    )
    if total == 0:
        status = "needs_material"
    elif compatible:
        status = "ready"
    else:
        status = "partial"
    return {
        "status": status,
        "counts": {
            "images": images,
            "videos": raw_videos,
            "gallery_images": gallery_images,
            "raw_assets": len(raws),
            "instagram_materialized": instagram_materialized,
            "total": total,
        },
    }
