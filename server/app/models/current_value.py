from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TagCurrentValue(Base):
    __tablename__ = "tag_current_values"
    __table_args__ = (
        CheckConstraint(
            "source IS NULL OR source IN ('simulator','modbus_rtu','modbus_tcp')", name="source"
        ),
        CheckConstraint(
            "quality IN ('GOOD','STALE','BAD','COMM_ERROR','DISABLED')", name="quality"
        ),
        CheckConstraint(
            "(CASE WHEN value_numeric IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN value_text IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN value_boolean IS NOT NULL THEN 1 ELSE 0 END) <= 1",
            name="one_value_type",
        ),
        CheckConstraint(
            "quality <> 'GOOD' OR ((value_numeric IS NOT NULL OR value_text IS NOT NULL "
            "OR value_boolean IS NOT NULL) AND source_timestamp IS NOT NULL AND error IS NULL)",
            name="good_has_value",
        ),
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint(
            "value_numeric IS NULL OR (value_numeric > '-Infinity'::numeric "
            "AND value_numeric < 'Infinity'::numeric)",
            name="finite_numeric",
        ).ddl_if(dialect="postgresql"),
    )

    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="RESTRICT"), primary_key=True
    )
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric())
    value_text: Mapped[str | None] = mapped_column(Text)
    value_boolean: Mapped[bool | None]
    raw_value: Mapped[str | None] = mapped_column(Text)
    quality: Mapped[str] = mapped_column(String(12), index=True)
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    error: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(BigInteger, default=1, server_default="1")
    source: Mapped[str | None] = mapped_column(String(16))
