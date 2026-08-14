from __future__ import annotations

import json
import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Business,
    BusinessGalleryImage,
    BusinessGrowthSignal,
    BusinessReview,
    BusinessService,
    InstagramContent,
    InstagramContentVersion,
    InstagramContentVersionAsset,
    InstagramRawAsset,
    SocialContentProposal,
    User,
)
from app.schemas.social_content_generation import EditorialPackageEdit
from app.services.instagram_content_service import (
    create_content,
    current_version,
    invalidate_validation,
    require_service_enabled,
)

GENERATOR_VERSION = "deterministic_v1"
PACKAGE_SCHEMA_VERSION = 1
MAX_PACKAGE_CHARS = 20_000
EDITORIAL_FORMATS = ("reel", "story", "carousel", "static_post")
DB_FORMAT = {
    "reel": "reel",
    "story": "story",
    "carousel": "carousel",
    "static_post": "single_image",
}

CTA_TEXT = {
    "book_now": "Reserva tu cita",
    "check_availability": "Consulta disponibilidad",
    "contact_us": "Escríbenos para más información",
    "learn_more": "Descubre más",
    "discover_service": "Conoce este servicio",
    "none": "",
}

ANGLE_LABEL = {
    "availability": "disponibilidad",
    "before_after": "resultado y proceso",
    "process": "proceso",
    "faq": "pregunta frecuente",
    "benefit": "beneficio",
    "testimonial": "experiencia de clientes",
    "seasonal": "momento de temporada",
    "limited_window": "momento oportuno",
    "educational": "consejo práctico",
    "behind_the_scenes": "detrás de escena",
}

HOOKS = (
    "Una idea sencilla para cuidar de ti",
    "¿Te apetece descubrir algo nuevo?",
    "Lo esencial, explicado de forma clara",
    "Un vistazo a cómo trabajamos",
    "Tu próxima cita puede empezar aquí",
    "Una pregunta frecuente, una respuesta útil",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _object(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _package_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_PACKAGE_CHARS:
        raise HTTPException(status_code=422, detail="Editorial package is too large")
    return encoded


def _slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_value.lower())[:50]


@dataclass(frozen=True)
class GenerationContext:
    business: Business
    proposal: SocialContentProposal
    snapshot: dict[str, Any]
    editorial_format: str
    hook: str
    assets: list[dict[str, Any]]
    missing_assets: list[str]
    warnings: list[str]


class ContentGenerator(Protocol):
    version: str

    def generate(self, context: GenerationContext) -> dict[str, Any]: ...


class DeterministicContentGenerator:
    version = GENERATOR_VERSION

    def generate(self, context: GenerationContext) -> dict[str, Any]:
        proposal = context.proposal
        business = context.business
        service_name = str((context.snapshot.get("service") or {}).get("name") or "").strip() or (
            proposal.service.name if proposal.service else "nuestro trabajo"
        )
        angle = str(context.snapshot.get("angle_code") or proposal.angle_code)
        cta_code = str(context.snapshot.get("recommended_cta") or proposal.recommended_cta)
        cta_text = CTA_TEXT.get(cta_code, "")
        angle_text = ANGLE_LABEL.get(angle, "idea útil")
        headline = f"{service_name}: {angle_text}"[:200]
        caption_parts = [
            context.hook,
            f"En {business.name} compartimos una mirada cercana sobre {service_name.lower()}.",
            "Te contamos lo importante con claridad para que puedas decidir con tranquilidad.",
        ]
        if cta_text:
            caption_parts.append(f"{cta_text}.")
        hashtags = _hashtags(business, proposal.service)
        package: dict[str, Any] = {
            "schema_version": PACKAGE_SCHEMA_VERSION,
            "editorial_format": context.editorial_format,
            "hook": context.hook,
            "headline": headline,
            "caption": "\n\n".join(caption_parts),
            "cta": {"code": cta_code, "text": cta_text},
            "angle": {"code": angle, "label": angle_text},
            "on_screen_text": [],
            "visual_direction": (
                "Usar material real del negocio, luz natural y encuadres limpios. "
                "Mantener un mensaje descriptivo y verificable, sin promesas comerciales."
            ),
            "shot_list": [],
            "slides": [],
            "story_frames": [],
            "hashtags": hashtags,
            "asset_plan": {
                "recommended": context.assets,
                "missing": context.missing_assets,
                "media_generation_requested": False,
            },
            "generation_context": {
                "proposal_id": proposal.id,
                "service_id": proposal.service_id,
                "source_signal_ids": [link.signal_id for link in proposal.signal_links],
                "source_event_id": proposal.source_event_id,
                "source_review_id": proposal.source_review_id,
                "accepted_at": proposal.accepted_at.isoformat() if proposal.accepted_at else None,
                "generator_version": self.version,
                "warnings": context.warnings,
            },
        }
        _add_format_structure(package, service_name, cta_text)
        return package


def _hashtags(business: Business, service: BusinessService | None) -> list[str]:
    candidates = [business.name, business.category or "negocio local", "bienestar"]
    if service:
        candidates.extend((service.name, service.category or "servicios"))
    if business.city:
        candidates.append(business.city)
    result: list[str] = []
    for value in candidates:
        token = _slug(value)
        if token and f"#{token}" not in result:
            result.append(f"#{token}")
    for fallback in ("#cuidarte", "#experiencialocal", "#reservatucita"):
        if fallback not in result:
            result.append(fallback)
    return result[:8]


def _add_format_structure(package: dict[str, Any], service_name: str, cta_text: str) -> None:
    editorial_format = package["editorial_format"]
    if editorial_format == "reel":
        package["on_screen_text"] = [package["hook"], package["headline"], cta_text]
        package["shot_list"] = [
            "Plano de apertura del espacio o preparación",
            f"Detalle real del proceso de {service_name}",
            "Cierre con el equipo o el espacio y el CTA",
        ]
    elif editorial_format == "story":
        package["story_frames"] = [
            {
                "text": package["hook"],
                "visual": "Imagen real de apertura",
                "cta": "",
                "sticker": "",
            },
            {
                "text": package["headline"],
                "visual": "Detalle real del servicio",
                "cta": "",
                "sticker": "Pregunta",
            },
            {
                "text": cta_text or "Gracias por vernos",
                "visual": "Cierre de marca",
                "cta": cta_text,
                "sticker": "Enlace" if cta_text else "",
            },
        ]
    elif editorial_format == "carousel":
        package["slides"] = [
            {
                "title": package["hook"],
                "body": "Una introducción breve y clara.",
                "visual": "Portada con material real",
            },
            {
                "title": "Lo importante",
                "body": f"Qué conviene saber sobre {service_name}.",
                "visual": "Detalle del proceso",
            },
            {
                "title": "Siguiente paso",
                "body": cta_text or "Guarda esta información",
                "visual": "Cierre de marca",
            },
        ]
    else:
        package["on_screen_text"] = [package["headline"]]


def _recent_hooks(db: Session, business_id: int) -> set[str]:
    rows = (
        db.query(InstagramContentVersion.editorial_package_json)
        .filter(
            InstagramContentVersion.business_id == business_id,
            InstagramContentVersion.editorial_package_json.is_not(None),
        )
        .order_by(InstagramContentVersion.created_at.desc(), InstagramContentVersion.id.desc())
        .limit(12)
        .all()
    )
    return {
        str(_object(raw).get("hook", "")).strip().casefold()
        for (raw,) in rows
        if str(_object(raw).get("hook", "")).strip()
    }


def _choose_hook(db: Session, business_id: int, seed: int) -> str:
    recent = _recent_hooks(db, business_id)
    ordered = [HOOKS[(seed + offset) % len(HOOKS)] for offset in range(len(HOOKS))]
    return next((item for item in ordered if item.casefold() not in recent), ordered[0])


def _freshness_warnings(db: Session, proposal: SocialContentProposal) -> list[str]:
    warnings: list[str] = []
    for link in proposal.signal_links:
        signal = db.get(BusinessGrowthSignal, link.signal_id)
        if signal is None or signal.status != "active":
            warnings.append(f"source_signal_{link.signal_id}_changed")
    return warnings


def _validate_source(db: Session, proposal: SocialContentProposal, now: datetime) -> dict[str, Any]:
    if proposal.status != "accepted":
        raise HTTPException(
            status_code=409, detail="Only an accepted proposal can generate content"
        )
    if _aware(proposal.expires_at) <= _aware(now):
        raise HTTPException(status_code=409, detail="The accepted proposal has expired")
    snapshot = _object(proposal.accepted_context_json)
    if not snapshot:
        raise HTTPException(status_code=409, detail="Accepted proposal snapshot is missing")
    if proposal.service_id is not None:
        service = db.get(BusinessService, proposal.service_id)
        if (
            service is None
            or service.business_id != proposal.business_id
            or not service.active
            or service.archived_at is not None
        ):
            raise HTTPException(status_code=409, detail="The proposal service is no longer active")
    if proposal.source_review_id is not None:
        review = db.get(BusinessReview, proposal.source_review_id)
        if (
            review is None
            or review.business_id != proposal.business_id
            or review.status != "usable"
            or not review.social_use_approved
        ):
            raise HTTPException(status_code=409, detail="The source review is no longer usable")
    return snapshot


def _recommended_assets(
    db: Session, proposal: SocialContentProposal, editorial_format: str
) -> tuple[list[dict[str, Any]], list[str]]:
    image_types = {"image/jpeg", "image/png", "image/webp"}
    rows: list[tuple[int, datetime, bool, dict[str, Any]]] = []
    for asset in db.query(InstagramRawAsset).filter(
        InstagramRawAsset.business_id == proposal.business_id,
        InstagramRawAsset.active.is_(True),
    ):
        compatible = (
            asset.media_type.startswith("video/")
            if editorial_format == "reel"
            else asset.media_type in image_types
        )
        rows.append(
            (
                int(asset.service_id == proposal.service_id and proposal.service_id is not None),
                asset.created_at,
                compatible,
                {
                    "source": "instagram_raw_asset",
                    "id": asset.id,
                    "media_type": asset.media_type,
                    "service_id": asset.service_id,
                },
            )
        )
    for gallery_asset in db.query(BusinessGalleryImage).filter(
        BusinessGalleryImage.business_id == proposal.business_id,
        BusinessGalleryImage.active.is_(True),
    ):
        rows.append(
            (
                int(
                    gallery_asset.service_id == proposal.service_id
                    and proposal.service_id is not None
                ),
                gallery_asset.created_at,
                editorial_format != "reel",
                {
                    "source": "business_gallery_image",
                    "id": gallery_asset.id,
                    "media_type": "image",
                    "service_id": gallery_asset.service_id,
                },
            )
        )
    ranked = sorted(rows, key=lambda item: (item[0], item[1], item[2]), reverse=True)
    recommended = [item[3] for item in ranked if item[2]][:8]
    missing: list[str] = []
    if editorial_format == "reel" and not recommended:
        missing.append("new_video")
    elif editorial_format == "carousel" and len(recommended) < 2:
        missing.append("new_photos_for_carousel")
    elif not recommended:
        missing.append("new_photo")
    return recommended, missing


def _format_from_snapshot(snapshot: dict[str, Any], requested: str | None) -> str:
    recommended = snapshot.get("recommended_formats")
    choices = (
        [item for item in recommended if item in EDITORIAL_FORMATS]
        if isinstance(recommended, list)
        else []
    )
    selected = requested or (choices[0] if choices else "static_post")
    if selected not in EDITORIAL_FORMATS:
        raise HTTPException(status_code=422, detail="Unsupported editorial format")
    return selected


def generate_from_proposal(
    db: Session,
    *,
    proposal: SocialContentProposal,
    actor: User,
    requested_format: str | None = None,
    generator: ContentGenerator | None = None,
    now: datetime | None = None,
) -> tuple[InstagramContent, InstagramContentVersion, bool]:
    require_service_enabled(db, proposal.business_id)
    snapshot = _validate_source(db, proposal, now or utc_now())
    existing = proposal.generated_content
    if existing is not None:
        return existing, current_version(db, existing), True
    editorial_format = _format_from_snapshot(snapshot, requested_format)
    assets, missing = _recommended_assets(db, proposal, editorial_format)
    context = GenerationContext(
        business=proposal.business,
        proposal=proposal,
        snapshot=snapshot,
        editorial_format=editorial_format,
        hook=_choose_hook(db, proposal.business_id, proposal.id),
        assets=assets,
        missing_assets=missing,
        warnings=_freshness_warnings(db, proposal),
    )
    selected_generator = generator or DeterministicContentGenerator()
    package = selected_generator.generate(context)
    content = create_content(
        db,
        business_id=proposal.business_id,
        actor=actor,
        title=package["headline"],
        caption=package["caption"],
        format=DB_FORMAT[editorial_format],
        planned_publish_at=None,
    )
    content.source_proposal_id = proposal.id
    version = current_version(db, content)
    version.editorial_package_json = _package_json(package)
    version.generation_source = "generated"
    version.generator_version = selected_generator.version
    db.flush()
    return content, version, False


def _new_generated_version(
    db: Session,
    *,
    content: InstagramContent,
    actor: User,
    package: dict[str, Any],
    generation_source: str,
    generator_version: str,
) -> InstagramContentVersion:
    previous = current_version(db, content)
    version = InstagramContentVersion(
        business_id=content.business_id,
        content_id=content.id,
        version_number=previous.version_number + 1,
        caption=str(package["caption"]),
        format=DB_FORMAT[str(package["editorial_format"])],
        editorial_package_json=_package_json(package),
        generation_source=generation_source,
        generator_version=generator_version,
        created_by_user_id=actor.id,
    )
    db.add(version)
    db.flush()
    for link in previous.asset_links:
        db.add(
            InstagramContentVersionAsset(
                version_id=version.id,
                asset_id=link.asset_id,
                position=link.position,
                is_cover=link.is_cover,
            )
        )
    invalidate_validation(db, content, "generated_content_changed")
    from app.services.instagram_publish_service import cancel_publish_job

    cancel_publish_job(db, content, reason="generated_content_changed", actor=actor)
    content.status = "draft"
    content.updated_at = utc_now()
    return version


def regenerate_content(
    db: Session,
    *,
    content: InstagramContent,
    actor: User,
    requested_format: str | None = None,
    generator: ContentGenerator | None = None,
    now: datetime | None = None,
) -> InstagramContentVersion:
    if content.status in {"cancelled", "published"}:
        raise HTTPException(status_code=409, detail="Terminal content cannot be regenerated")
    if content.source_proposal is None:
        raise HTTPException(status_code=409, detail="Content was not generated from a proposal")
    snapshot = _validate_source(db, content.source_proposal, now or utc_now())
    editorial_format = _format_from_snapshot(snapshot, requested_format)
    assets, missing = _recommended_assets(db, content.source_proposal, editorial_format)
    context = GenerationContext(
        business=content.business,
        proposal=content.source_proposal,
        snapshot=snapshot,
        editorial_format=editorial_format,
        hook=_choose_hook(
            db,
            content.business_id,
            content.source_proposal.id + current_version(db, content).version_number,
        ),
        assets=assets,
        missing_assets=missing,
        warnings=_freshness_warnings(db, content.source_proposal),
    )
    selected_generator = generator or DeterministicContentGenerator()
    package = selected_generator.generate(context)
    return _new_generated_version(
        db,
        content=content,
        actor=actor,
        package=package,
        generation_source="regenerated",
        generator_version=selected_generator.version,
    )


def update_generated_draft(
    db: Session,
    *,
    content: InstagramContent,
    actor: User,
    edit: EditorialPackageEdit,
) -> tuple[InstagramContentVersion, bool]:
    if content.status in {"cancelled", "published"}:
        raise HTTPException(status_code=409, detail="Terminal content cannot be edited")
    previous = current_version(db, content)
    package = _object(previous.editorial_package_json)
    if not package or content.source_proposal_id is None:
        raise HTTPException(status_code=409, detail="Content has no generated editorial package")
    updated = deepcopy(package)
    values = edit.model_dump()
    for key in (
        "hook",
        "headline",
        "caption",
        "cta_text",
        "on_screen_text",
        "visual_direction",
        "shot_list",
        "slides",
        "story_frames",
        "hashtags",
    ):
        updated[key] = values[key]
    updated["cta"] = {**dict(updated.get("cta") or {}), "text": edit.cta_text}
    _validate_edited_structure(updated)
    if _package_json(updated) == _package_json(package):
        return previous, False
    version = _new_generated_version(
        db,
        content=content,
        actor=actor,
        package=updated,
        generation_source="manual_edit",
        generator_version=previous.generator_version or GENERATOR_VERSION,
    )
    content.title = edit.headline or content.title
    return version, True


def _validate_edited_structure(package: dict[str, Any]) -> None:
    editorial_format = package.get("editorial_format")
    valid = (
        (editorial_format == "reel" and package.get("shot_list") and package.get("on_screen_text"))
        or (editorial_format == "story" and package.get("story_frames"))
        or (editorial_format == "carousel" and len(package.get("slides") or []) >= 2)
        or (editorial_format == "static_post" and package.get("on_screen_text"))
    )
    if not valid:
        raise HTTPException(
            status_code=422,
            detail="Editorial structure does not match the generated content format",
        )


def serialize_editorial_package(version: InstagramContentVersion) -> dict[str, Any] | None:
    return _object(version.editorial_package_json) if version.editorial_package_json else None
