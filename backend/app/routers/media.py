from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import get_settings, get_uploads_dir
from app.core.database import get_db
from app.core.security import get_current_user, require_business_admin, require_owner
from app.models import Business, BusinessGalleryImage, User
from app.schemas.branding import GalleryImageUpdate

router = APIRouter(tags=["business-media"])
ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_LOGO_BYTES = min(3, get_settings().upload_max_size_mb) * 1024 * 1024
MAX_GALLERY_BYTES = get_settings().upload_max_size_mb * 1024 * 1024
MAX_ACTIVE_GALLERY = 10


def business_or_404(db: Session, slug: str, *, public: bool = False) -> Business:
    query = db.query(Business).filter(Business.slug == slug)
    if public:
        query = query.filter(Business.status == "active")
    business = query.first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


async def read_image(file: UploadFile, max_bytes: int) -> tuple[bytes, str]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES or file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Solo se permiten imágenes JPG, PNG o WEBP")
    content = await file.read(max_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="El archivo está vacío")
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400, detail=f"La imagen supera el límite de {max_bytes // 1024 // 1024} MB"
        )
    signatures = {
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP",
    }
    if not signatures[file.content_type]:
        raise HTTPException(
            status_code=400, detail="El contenido del archivo no coincide con una imagen válida"
        )
    return content, ALLOWED_TYPES[file.content_type]


def serialize_image(image: BusinessGalleryImage) -> dict:
    return {
        "id": image.id,
        "url": image.url,
        "alt_text": image.alt_text,
        "position": image.position,
        "active": image.active,
        "created_at": image.created_at.isoformat(),
    }


async def upload_logo_impl(slug: str, file: UploadFile, db: Session) -> dict:
    business = business_or_404(db, slug)
    content, extension = await read_image(file, MAX_LOGO_BYTES)
    directory = get_uploads_dir() / "businesses" / business.slug / "logo"
    directory.mkdir(parents=True, exist_ok=True)
    for old_file in directory.glob("logo.*"):
        old_file.unlink(missing_ok=True)
    path = directory / f"logo{extension}"
    path.write_bytes(content)
    business.logo_url = f"/uploads/businesses/{business.slug}/logo/{path.name}"
    db.commit()
    return {"ok": True, "logo_url": business.logo_url, "logo_alt": business.logo_alt}


def delete_logo_impl(slug: str, db: Session) -> dict:
    business = business_or_404(db, slug)
    directory = get_uploads_dir() / "businesses" / business.slug / "logo"
    if directory.exists():
        for old_file in directory.glob("logo.*"):
            old_file.unlink(missing_ok=True)
    business.logo_url = None
    db.commit()
    return {"ok": True, "logo_url": None}


def list_gallery_impl(slug: str, db: Session, *, public: bool = False) -> dict:
    business = business_or_404(db, slug, public=public)
    query = db.query(BusinessGalleryImage).filter(BusinessGalleryImage.business_id == business.id)
    if public:
        query = query.filter(BusinessGalleryImage.active.is_(True))
    images = query.order_by(
        BusinessGalleryImage.position.asc(), BusinessGalleryImage.id.asc()
    ).all()
    return {"business_slug": business.slug, "images": [serialize_image(image) for image in images]}


async def upload_gallery_impl(
    slug: str, file: UploadFile, alt_text: str | None, db: Session
) -> dict:
    business = business_or_404(db, slug)
    active_count = (
        db.query(BusinessGalleryImage)
        .filter(
            BusinessGalleryImage.business_id == business.id, BusinessGalleryImage.active.is_(True)
        )
        .count()
    )
    if active_count >= MAX_ACTIVE_GALLERY:
        raise HTTPException(status_code=400, detail="Máximo 10 imágenes activas por negocio")
    content, extension = await read_image(file, MAX_GALLERY_BYTES)
    directory = get_uploads_dir() / "businesses" / business.slug / "gallery"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid4().hex}{extension}"
    path.write_bytes(content)
    image = BusinessGalleryImage(
        business_id=business.id,
        url=f"/uploads/businesses/{business.slug}/gallery/{path.name}",
        alt_text=alt_text.strip()[:240] or None if alt_text else None,
        position=active_count,
        active=True,
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return {"ok": True, "image": serialize_image(image)}


def patch_gallery_impl(slug: str, image_id: int, payload: GalleryImageUpdate, db: Session) -> dict:
    business = business_or_404(db, slug)
    image = (
        db.query(BusinessGalleryImage)
        .filter(
            BusinessGalleryImage.id == image_id, BusinessGalleryImage.business_id == business.id
        )
        .first()
    )
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("active") is True and not image.active:
        active_count = (
            db.query(BusinessGalleryImage)
            .filter(
                BusinessGalleryImage.business_id == business.id,
                BusinessGalleryImage.active.is_(True),
            )
            .count()
        )
        if active_count >= MAX_ACTIVE_GALLERY:
            raise HTTPException(status_code=400, detail="Máximo 10 imágenes activas por negocio")
    for field, value in updates.items():
        setattr(image, field, value)
    db.commit()
    db.refresh(image)
    return {"ok": True, "image": serialize_image(image)}


def delete_gallery_impl(slug: str, image_id: int, db: Session) -> dict:
    business = business_or_404(db, slug)
    image = (
        db.query(BusinessGalleryImage)
        .filter(
            BusinessGalleryImage.id == image_id, BusinessGalleryImage.business_id == business.id
        )
        .first()
    )
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    relative = image.url.removeprefix("/uploads/")
    path = (get_uploads_dir() / relative).resolve()
    if get_uploads_dir().resolve() in path.parents:
        path.unlink(missing_ok=True)
    db.delete(image)
    db.commit()
    return {"ok": True}


@router.get("/api/businesses/{business_slug}/media/gallery")
def public_gallery(business_slug: str, db: Session = Depends(get_db)):
    return list_gallery_impl(business_slug, db, public=True)


@router.post(
    "/api/admin/businesses/{business_slug}/media/logo",
    dependencies=[Depends(require_business_admin)],
)
@router.post(
    "/api/owner/businesses/{business_slug}/media/logo", dependencies=[Depends(require_owner)]
)
async def upload_logo(
    business_slug: str,
    request: Request,
    file: UploadFile = File(...),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = await upload_logo_impl(business_slug, file, db)
    business = business_or_404(db, business_slug)
    record_audit(
        db,
        action="media_uploaded",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business_logo",
        resource_id=business.id,
    )
    return result


@router.delete(
    "/api/admin/businesses/{business_slug}/media/logo",
    dependencies=[Depends(require_business_admin)],
)
@router.delete(
    "/api/owner/businesses/{business_slug}/media/logo", dependencies=[Depends(require_owner)]
)
def delete_logo(
    business_slug: str,
    request: Request,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    result = delete_logo_impl(business_slug, db)
    record_audit(
        db,
        action="media_deleted",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business_logo",
        resource_id=business.id,
    )
    return result


@router.get(
    "/api/admin/businesses/{business_slug}/media/gallery",
    dependencies=[Depends(require_business_admin)],
)
@router.get(
    "/api/owner/businesses/{business_slug}/media/gallery", dependencies=[Depends(require_owner)]
)
def list_gallery(business_slug: str, db: Session = Depends(get_db)):
    return list_gallery_impl(business_slug, db)


@router.post(
    "/api/admin/businesses/{business_slug}/media/gallery",
    dependencies=[Depends(require_business_admin)],
)
@router.post(
    "/api/owner/businesses/{business_slug}/media/gallery", dependencies=[Depends(require_owner)]
)
async def upload_gallery(
    business_slug: str,
    request: Request,
    file: UploadFile = File(...),
    alt_text: str | None = Form(default=None),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = await upload_gallery_impl(business_slug, file, alt_text, db)
    business = business_or_404(db, business_slug)
    record_audit(
        db,
        action="media_uploaded",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="gallery_image",
        resource_id=result["image"]["id"],
    )
    return result


@router.patch(
    "/api/admin/businesses/{business_slug}/media/gallery/{image_id}",
    dependencies=[Depends(require_business_admin)],
)
@router.patch(
    "/api/owner/businesses/{business_slug}/media/gallery/{image_id}",
    dependencies=[Depends(require_owner)],
)
def patch_gallery(
    business_slug: str, image_id: int, payload: GalleryImageUpdate, db: Session = Depends(get_db)
):
    return patch_gallery_impl(business_slug, image_id, payload, db)


@router.delete(
    "/api/admin/businesses/{business_slug}/media/gallery/{image_id}",
    dependencies=[Depends(require_business_admin)],
)
@router.delete(
    "/api/owner/businesses/{business_slug}/media/gallery/{image_id}",
    dependencies=[Depends(require_owner)],
)
def delete_gallery(
    business_slug: str,
    image_id: int,
    request: Request,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    result = delete_gallery_impl(business_slug, image_id, db)
    record_audit(
        db,
        action="media_deleted",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="gallery_image",
        resource_id=image_id,
    )
    return result
