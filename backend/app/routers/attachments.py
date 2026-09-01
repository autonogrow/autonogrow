from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import get_settings, get_uploads_dir
from app.core.database import get_db
from app.core.security import (
    get_optional_current_user,
    require_business_operational_status,
)
from app.models import (
    Booking,
    BookingAttachment,
    Business,
    BusinessUser,
    CustomerAccountLink,
    User,
)
from app.services.booking_manage_token_service import booking_manage_token_is_valid

router = APIRouter(
    prefix="/api/businesses/{business_slug}/bookings/{booking_id}/attachments",
    tags=["attachments"],
)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

MAX_FILE_SIZE_BYTES = get_settings().upload_max_size_mb * 1024 * 1024
MAX_FILES_PER_REQUEST = 5


def image_signature_matches(content: bytes, content_type: str) -> bool:
    signatures = {
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP",
    }
    return signatures.get(content_type, False)


def can_access_booking_attachments(
    db: Session,
    *,
    booking: Booking,
    user: User | None,
    booking_token: str | None,
) -> bool:
    if user is not None and user.is_active:
        if user.is_owner or booking.customer_user_id == user.id:
            return True
        account_link = (
            db.query(CustomerAccountLink.id)
            .filter(
                CustomerAccountLink.business_id == booking.business_id,
                CustomerAccountLink.customer_id == booking.customer_id,
                CustomerAccountLink.user_id == user.id,
            )
            .first()
        )
        if account_link is not None:
            return True
        membership = (
            db.query(BusinessUser)
            .filter(
                BusinessUser.business_id == booking.business_id,
                BusinessUser.user_id == user.id,
                BusinessUser.active.is_(True),
            )
            .first()
        )
        if membership is not None:
            return membership.role == "business_admin" or (
                membership.role == "business_staff"
                and booking.staff_business_user_id == membership.id
            )
    return booking_manage_token_is_valid(booking, booking_token)


def raise_attachment_access_error(*, current_user: User | None, booking_token: str | None) -> None:
    if current_user is None and not booking_token:
        raise HTTPException(status_code=401, detail="Booking attachment authorization required")
    if current_user is None:
        raise HTTPException(status_code=404, detail="El enlace ya no es válido.")
    raise HTTPException(status_code=403, detail="You cannot access files for this booking")


def get_attachment_context(
    db: Session,
    *,
    business_slug: str,
    booking_id: int,
    current_user: User | None,
    booking_token: str | None,
) -> tuple[Business, Booking]:
    business = db.query(Business).filter(Business.slug == business_slug).first()
    if business is None:
        if current_user is None:
            raise_attachment_access_error(current_user=current_user, booking_token=booking_token)
        raise HTTPException(status_code=404, detail="Business not found")
    booking = (
        db.query(Booking)
        .filter(
            Booking.id == booking_id,
            Booking.business_id == business.id,
        )
        .first()
    )
    if booking is None:
        if current_user is None:
            raise_attachment_access_error(current_user=current_user, booking_token=booking_token)
        raise HTTPException(status_code=404, detail="Booking not found")
    return business, booking


def private_attachment_url(business_slug: str, booking_id: int, attachment_id: int) -> str:
    return (
        f"/api/businesses/{business_slug}/bookings/{booking_id}/attachments/{attachment_id}/content"
    )


@router.post("", dependencies=[Depends(require_business_operational_status)])
async def upload_booking_attachments(
    business_slug: str,
    booking_id: int,
    request: Request,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    booking_token: str | None = Header(default=None, alias="X-Booking-Token"),
):
    business, booking = get_attachment_context(
        db,
        business_slug=business_slug,
        booking_id=booking_id,
        current_user=current_user,
        booking_token=booking_token,
    )

    if not can_access_booking_attachments(
        db,
        booking=booking,
        user=current_user,
        booking_token=booking_token,
    ):
        raise_attachment_access_error(current_user=current_user, booking_token=booking_token)

    if not files:
        return {
            "ok": True,
            "message": "No se subieron archivos.",
            "attachments": [],
        }

    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"Máximo {MAX_FILES_PER_REQUEST} fotos por solicitud.",
        )

    validated_files: list[tuple[UploadFile, bytes, str, str]] = []
    for file in files:
        content_type = file.content_type

        if content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de archivo no permitido: {content_type}",
            )

        content = await file.read(MAX_FILE_SIZE_BYTES + 1)
        size_bytes = len(content)

        if not content:
            raise HTTPException(status_code=400, detail=f"El archivo {file.filename} está vacío.")

        if size_bytes > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"El archivo {file.filename} supera el límite de {get_settings().upload_max_size_mb} MB.",
            )

        if not image_signature_matches(content, content_type):
            raise HTTPException(
                status_code=400, detail=f"Contenido de imagen inválido: {file.filename}"
            )

        extension = ALLOWED_CONTENT_TYPES[content_type]
        stored_filename = f"{uuid4().hex}{extension}"
        validated_files.append((file, content, content_type, stored_filename))

    upload_dir = get_uploads_dir() / business.slug / str(booking.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    created_attachments = []
    written_paths = []
    try:
        for file, content, content_type, stored_filename in validated_files:
            file_path = upload_dir / stored_filename
            written_paths.append(file_path)
            file_path.write_bytes(content)

            attachment = BookingAttachment(
                business_id=business.id,
                booking_id=booking.id,
                original_filename=Path(file.filename or stored_filename).name[:300],
                stored_filename=stored_filename,
                file_path=str(file_path),
                content_type=content_type,
                size_bytes=len(content),
            )

            db.add(attachment)
            db.flush()

            created_attachments.append(
                {
                    "id": attachment.id,
                    "original_filename": attachment.original_filename,
                    "stored_filename": attachment.stored_filename,
                    "content_type": attachment.content_type,
                    "size_bytes": attachment.size_bytes,
                    "url": private_attachment_url(business.slug, booking.id, attachment.id),
                }
            )
        db.commit()
    except Exception:
        db.rollback()
        for path in written_paths:
            path.unlink(missing_ok=True)
        raise
    record_audit(
        db,
        action="media_uploaded",
        request=request,
        actor=current_user,
        business_id=business.id,
        resource_type="booking_attachment",
        resource_id=booking.id,
        metadata={"file_count": len(created_attachments)},
    )

    return {
        "ok": True,
        "message": "Fotos subidas correctamente.",
        "attachments": created_attachments,
    }


@router.get("")
def list_booking_attachments(
    business_slug: str,
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    booking_token: str | None = Header(default=None, alias="X-Booking-Token"),
):
    business, booking = get_attachment_context(
        db,
        business_slug=business_slug,
        booking_id=booking_id,
        current_user=current_user,
        booking_token=booking_token,
    )
    if not can_access_booking_attachments(
        db,
        booking=booking,
        user=current_user,
        booking_token=booking_token,
    ):
        raise_attachment_access_error(current_user=current_user, booking_token=booking_token)

    attachments = (
        db.query(BookingAttachment)
        .filter(
            BookingAttachment.business_id == business.id,
            BookingAttachment.booking_id == booking.id,
        )
        .order_by(BookingAttachment.created_at.asc())
        .all()
    )

    return {
        "business_slug": business.slug,
        "booking_id": booking.id,
        "attachments": [
            {
                "id": attachment.id,
                "original_filename": attachment.original_filename,
                "stored_filename": attachment.stored_filename,
                "content_type": attachment.content_type,
                "size_bytes": attachment.size_bytes,
                "url": private_attachment_url(business.slug, booking.id, attachment.id),
            }
            for attachment in attachments
        ],
    }


@router.get("/{attachment_id}/content")
def get_booking_attachment_content(
    business_slug: str,
    booking_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    booking_token: str | None = Header(default=None, alias="X-Booking-Token"),
):
    business, booking = get_attachment_context(
        db,
        business_slug=business_slug,
        booking_id=booking_id,
        current_user=current_user,
        booking_token=booking_token,
    )
    if not can_access_booking_attachments(
        db, booking=booking, user=current_user, booking_token=booking_token
    ):
        raise_attachment_access_error(current_user=current_user, booking_token=booking_token)

    attachment = (
        db.query(BookingAttachment)
        .filter(
            BookingAttachment.id == attachment_id,
            BookingAttachment.business_id == business.id,
            BookingAttachment.booking_id == booking.id,
        )
        .first()
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    uploads_root = get_uploads_dir().resolve()
    path = (uploads_root / business.slug / str(booking.id) / attachment.stored_filename).resolve()
    if uploads_root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment file not found")
    return FileResponse(path, media_type=attachment.content_type)
