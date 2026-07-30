from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, BackupRecord


def record_backup_manifest(db: Session, manifest: dict[str, Any]) -> BackupRecord:
    row = (
        db.query(BackupRecord)
        .filter(
            BackupRecord.backup_set_id == str(manifest["backup_set_id"]),
            BackupRecord.backup_type == str(manifest["backup_type"]),
        )
        .first()
    )
    if row is None:
        row = BackupRecord(
            backup_set_id=str(manifest["backup_set_id"])[:80],
            backup_type=str(manifest["backup_type"]),
            environment=str(manifest.get("environment", "unknown"))[:30],
            release_id=str(manifest.get("release_id", "unknown"))[:120],
            artifact_name=str(manifest["artifact_name"])[:255],
        )
        db.add(row)
    row.manifest_name = f"{row.artifact_name}.manifest.json"[:255]
    row.checksum_sha256 = str(manifest.get("sha256", ""))[:64] or None
    row.size_bytes = int(manifest.get("size_bytes", 0))
    row.status = str(manifest.get("status", "valid"))
    row.safe_details_json = json.dumps(
        {"format": manifest.get("format"), "files": manifest.get("files")},
        sort_keys=True,
    )
    db.flush()
    db.add(
        AuditLog(
            action="backup_created",
            resource_type="backup_record",
            resource_id=str(row.id),
            metadata_json=json.dumps(
                {"backup_set_id": row.backup_set_id, "backup_type": row.backup_type}
            ),
        )
    )
    return row


def record_backup_verification(
    db: Session, *, artifact_name: str, status: str, restore_test: bool = False
) -> BackupRecord | None:
    row = (
        db.query(BackupRecord)
        .filter(BackupRecord.artifact_name == artifact_name)
        .order_by(BackupRecord.created_at.desc())
        .first()
    )
    if row is None:
        return None
    now = datetime.utcnow()
    if restore_test:
        row.restore_test_status = status
        row.restore_tested_at = now
    else:
        row.verification_status = status
        row.verified_at = now
    row.updated_at = now
    db.flush()
    db.add(
        AuditLog(
            action="backup_restore_tested" if restore_test else "backup_verified",
            resource_type="backup_record",
            resource_id=str(row.id),
            metadata_json=json.dumps({"status": status}),
        )
    )
    return row
