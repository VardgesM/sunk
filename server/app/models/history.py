from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TagHistory(Base):
    __tablename__ = "tag_history"
    __table_args__ = (
        CheckConstraint(
            "source IS NULL OR source IN ('simulator','modbus_rtu','modbus_tcp')", name="source"
        ),
        Index("ix_tag_history_tag_recorded", "tag_id", "recorded_at", "id"),
        CheckConstraint(
            "quality IN ('GOOD','STALE','BAD','COMM_ERROR','DISABLED')", name="quality"
        ),
        CheckConstraint(
            "(CASE WHEN value_numeric IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN value_boolean IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN value_text IS NOT NULL THEN 1 ELSE 0 END) = CASE WHEN quality = 'GOOD' THEN 1 ELSE 0 END",
            name="typed_quality",
        ),
        CheckConstraint(
            "quality <> 'GOOD' OR source_timestamp IS NOT NULL", name="source_required"
        ),
        CheckConstraint(
            "value_numeric IS NULL OR (value_numeric > '-Infinity'::numeric AND value_numeric < 'Infinity'::numeric)",
            name="finite_numeric",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="RESTRICT"), index=True)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric())
    value_text: Mapped[str | None] = mapped_column(Text)
    value_boolean: Mapped[bool | None]
    quality: Mapped[str] = mapped_column(String(12))
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    raw_value: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(16))
