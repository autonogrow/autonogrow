from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_uploads_dir
from app.models import (
    Booking,
    BookingAttachment,
    Business,
    BusinessGalleryImage,
    InstagramFinalAsset,
    InstagramRawAsset,
)

DEFAULT_ORPHAN_GRACE_SECONDS = 24 * 60 * 60
RESERVED_UPLOAD_DIRECTORIES = {"_instagram_content", "businesses"}


def _safe_relative(root: Path, raw_path: str) -> tuple[str | None, str | None]:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return None, "absolute path"
    resolved = (root / candidate).resolve()
    if root != resolved and root not in resolved.parents:
        return None, "path escapes uploads root"
    return resolved.relative_to(root).as_posix(), None


def _internal_media_path(url: str | None) -> str | None:
    prefix = "/uploads/"
    return url.removeprefix(prefix) if url and url.startswith(prefix) else None


def _referenced_paths(db: Session, root: Path) -> tuple[set[str], list[dict[str, Any]]]:
    referenced: set[str] = set()
    invalid: list[dict[str, Any]] = []

    def add_reference(kind: str, row_id: int, raw_path: str) -> None:
        relative, reason = _safe_relative(root, raw_path)
        if reason is not None:
            invalid.append({"kind": kind, "id": row_id, "path": raw_path, "reason": reason})
        elif relative is not None:
            referenced.add(relative)

    for row in db.query(InstagramRawAsset.id, InstagramRawAsset.storage_key).all():
        add_reference("instagram_raw_asset", row.id, row.storage_key)
    for row in db.query(InstagramFinalAsset.id, InstagramFinalAsset.storage_key).all():
        add_reference("instagram_final_asset", row.id, row.storage_key)
    for row in db.query(Business.id, Business.logo_url).filter(Business.logo_url.is_not(None)).all():
        if relative := _internal_media_path(row.logo_url):
            add_reference("business_logo", row.id, relative)
    for row in db.query(BusinessGalleryImage.id, BusinessGalleryImage.url).all():
        if relative := _internal_media_path(row.url):
            add_reference("business_gallery", row.id, relative)
    attachment_rows = (
        db.query(BookingAttachment, Business.slug)
        .join(Booking, Booking.id == BookingAttachment.booking_id)
        .join(Business, Business.id == BookingAttachment.business_id)
        .all()
    )
    for attachment, business_slug in attachment_rows:
        if Path(attachment.stored_filename).name != attachment.stored_filename:
            invalid.append(
                {
                    "kind": "booking_attachment",
                    "id": attachment.id,
                    "path": attachment.stored_filename,
                    "reason": "invalid stored filename",
                }
            )
            continue
        add_reference(
            "booking_attachment",
            attachment.id,
            f"{business_slug}/{attachment.booking_id}/{attachment.stored_filename}",
        )
    return referenced, invalid


def _walk_files(root: Path, directory: Path) -> tuple[set[str], list[dict[str, str]]]:
    files: set[str] = set()
    invalid: list[dict[str, str]] = []
    if not directory.exists():
        return files, invalid
    for path in directory.rglob("*"):
        if path.is_symlink():
            invalid.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "reason": "symlink is not scanned or deleted",
                }
            )
            continue
        if not path.is_file():
            continue
        resolved = path.resolve()
        if root not in resolved.parents:
            invalid.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "reason": "file escapes uploads root",
                }
            )
            continue
        files.add(resolved.relative_to(root).as_posix())
    return files, invalid


def _managed_files(root: Path) -> tuple[set[str], list[dict[str, str]]]:
    files: set[str] = set()
    invalid: list[dict[str, str]] = []
    for managed_dir in RESERVED_UPLOAD_DIRECTORIES:
        found, unsafe = _walk_files(root, root / managed_dir)
        files.update(found)
        invalid.extend(unsafe)
    for business_dir in root.iterdir():
        if business_dir.name in RESERVED_UPLOAD_DIRECTORIES or business_dir.is_symlink():
            continue
        if not business_dir.is_dir():
            continue
        for booking_dir in business_dir.iterdir():
            if not booking_dir.name.isdigit() or booking_dir.is_symlink():
                continue
            found, unsafe = _walk_files(root, booking_dir)
            files.update(found)
            invalid.extend(unsafe)
    return files, invalid


def reconcile_managed_storage(
    db: Session,
    *,
    root: Path | None = None,
    apply: bool = False,
    now: datetime | None = None,
    orphan_grace_seconds: int = DEFAULT_ORPHAN_GRACE_SECONDS,
) -> dict[str, Any]:
    uploads_root = (root or get_uploads_dir()).resolve()
    uploads_root.mkdir(parents=True, exist_ok=True)
    referenced, invalid_database_paths = _referenced_paths(db, uploads_root)
    stored, invalid_storage_paths = _managed_files(uploads_root)
    missing_files = sorted(path for path in referenced if not (uploads_root / path).is_file())
    orphan_files = sorted(stored - referenced)
    effective_now = now or datetime.now(timezone.utc)
    cutoff = effective_now.timestamp() - orphan_grace_seconds
    cleanup_candidates = [
        relative
        for relative in orphan_files
        if (uploads_root / relative).stat().st_mtime <= cutoff
    ]
    deleted_files: list[str] = []
    if apply:
        current_referenced, _ = _referenced_paths(db, uploads_root)
        for relative in cleanup_candidates:
            if relative in current_referenced:
                continue
            path = (uploads_root / relative).resolve()
            if uploads_root not in path.parents or path.is_symlink() or not path.is_file():
                continue
            path.unlink()
            deleted_files.append(relative)
    return {
        "dry_run": not apply,
        "managed_root": str(uploads_root),
        "referenced_files": len(referenced),
        "stored_files": len(stored),
        "orphan_files": orphan_files,
        "cleanup_candidates": cleanup_candidates,
        "missing_files": missing_files,
        "invalid_database_paths": invalid_database_paths,
        "invalid_storage_paths": invalid_storage_paths,
        "deleted_files": deleted_files,
        "orphan_grace_seconds": orphan_grace_seconds,
    }
