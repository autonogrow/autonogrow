from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OperationalState(Base):
    __tablename__ = "operational_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    safe_reason: Mapped[str | None] = mapped_column(String(500))
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class BackupRecord(Base):
    __tablename__ = "backup_records"
    __table_args__ = (
        CheckConstraint("backup_type IN ('postgresql','uploads')", name="ck_backup_records_type"),
        CheckConstraint(
            "status IN ('creating','valid','invalid','warning','failed')",
            name="ck_backup_records_status",
        ),
        CheckConstraint("size_bytes >= 0", name="ck_backup_records_size"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    backup_set_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    backup_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(30), nullable=False)
    release_id: Mapped[str] = mapped_column(String(120), nullable=False)
    artifact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    manifest_name: Mapped[str | None] = mapped_column(String(255))
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="creating", index=True)
    protected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verification_status: Mapped[str | None] = mapped_column(String(30), index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    restore_test_status: Mapped[str | None] = mapped_column(String(30), index=True)
    restore_tested_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    safe_details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
