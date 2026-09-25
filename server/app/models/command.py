from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Command(Base):
    __tablename__ = "commands"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED','EXECUTING','VERIFYING','SUCCESS','FAILED','CANCELLED','EXPIRED')",
            name="status",
        ),
        CheckConstraint("source IN ('manual','automation','system')", name="source"),
        CheckConstraint("telemetry_mode IN ('simulator','modbus')", name="mode"),
        CheckConstraint("attempt_count >= 0 AND revision > 0", name="counters"),
        CheckConstraint(
            "(requested_numeric IS NOT NULL) != (requested_boolean IS NOT NULL)",
            name="requested_type",
        ),
        CheckConstraint(
            "previous_numeric IS NULL OR previous_boolean IS NULL", name="previous_type"
        ),
        CheckConstraint(
            "verified_numeric IS NULL OR verified_boolean IS NULL", name="verified_type"
        ),
        CheckConstraint(
            "status != 'SUCCESS' OR verified_numeric IS NOT NULL OR verified_boolean IS NOT NULL",
            name="success_value",
        ),
        CheckConstraint(
            "(status IN ('SUCCESS','FAILED','CANCELLED','EXPIRED')) = (completed_at IS NOT NULL)",
            name="completion",
        ),
        CheckConstraint(
            " AND ".join(
                f"({p}_numeric IS NULL OR {p}_numeric::text NOT IN ('NaN','Infinity','-Infinity'))"
                for p in ("requested", "previous", "verified")
            ),
            name="finite",
        ).ddl_if(dialect="postgresql"),
        Index("ix_commands_status_created_at", "status", "created_at"),
        Index("ix_commands_tag_created_at", "tag_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="RESTRICT"))
    requested_numeric: Mapped[Decimal | None] = mapped_column(Numeric())
    requested_boolean: Mapped[bool | None]
    previous_numeric: Mapped[Decimal | None] = mapped_column(Numeric())
    previous_boolean: Mapped[bool | None]
    verified_numeric: Mapped[Decimal | None] = mapped_column(Numeric())
    verified_boolean: Mapped[bool | None]
    status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    source: Mapped[str] = mapped_column(String(16), default="manual")
    telemetry_mode: Mapped[str] = mapped_column(String(16))
    physical_confirmed: Mapped[bool] = mapped_column(default=False)
    attempt_count: Mapped[int] = mapped_column(default=0)
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    tag_version: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    device_version: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    connection_version: Mapped[datetime] = mapped_column(DateTime(timezone=True))
