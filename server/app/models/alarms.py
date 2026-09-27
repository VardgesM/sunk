"""Alarm configuration, retained events and notification outbox."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.configuration import Timestamps


class AlarmRule(Timestamps, Base):
    __tablename__ = "alarm_rules"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="name"),
        CheckConstraint("operator IN ('>','>=','<','<=','==','!=')", name="operator"),
        CheckConstraint("severity IN ('INFO','WARNING','CRITICAL')", name="severity"),
        CheckConstraint("(value_numeric IS NOT NULL) != (value_boolean IS NOT NULL)", name="typed"),
        CheckConstraint("for_duration_ms IS NULL OR for_duration_ms >= 0", name="duration"),
        CheckConstraint("hysteresis >= 0", name="hysteresis"),
        CheckConstraint(
            "value_boolean IS NULL OR (operator IN ('==','!=') AND hysteresis = 0)", name="boolean"
        ),
        CheckConstraint("operator NOT IN ('==','!=') OR hysteresis = 0", name="equality"),
        CheckConstraint(
            "(value_numeric IS NULL OR value_numeric::text NOT IN ('NaN','Infinity','-Infinity')) AND hysteresis::text NOT IN ('NaN','Infinity','-Infinity')",
            name="finite",
        ).ddl_if(dialect="postgresql"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="RESTRICT"), index=True)
    operator: Mapped[str] = mapped_column(String(2))
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric())
    value_boolean: Mapped[bool | None]
    severity: Mapped[str] = mapped_column(String(8))
    enabled: Mapped[bool] = mapped_column(default=False, index=True)
    for_duration_ms: Mapped[int | None]
    hysteresis: Mapped[Decimal] = mapped_column(Numeric(), default=0)
    notification_enabled: Mapped[bool] = mapped_column(default=False)


class AlarmRuntime(Base):
    __tablename__ = "alarm_runtime"
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("alarm_rules.id", ondelete="RESTRICT"), primary_key=True
    )
    true_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlarmEvent(Base):
    __tablename__ = "alarm_events"
    __table_args__ = (
        CheckConstraint("state IN ('ACTIVE','ACKNOWLEDGED','CLEARED')", name="state"),
        CheckConstraint("severity IN ('INFO','WARNING','CRITICAL')", name="severity"),
        CheckConstraint("(value_numeric IS NOT NULL) != (value_boolean IS NOT NULL)", name="typed"),
        CheckConstraint("(state = 'CLEARED') = (cleared_at IS NOT NULL)", name="cleared"),
        CheckConstraint(
            "state != 'ACKNOWLEDGED' OR acknowledged_at IS NOT NULL", name="acknowledged"
        ),
        Index(
            "uq_alarm_events_open_rule",
            "rule_id",
            unique=True,
            postgresql_where=text("state != 'CLEARED'"),
            sqlite_where=text("state != 'CLEARED'"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("alarm_rules.id", ondelete="RESTRICT"), index=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    tag_name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str | None] = mapped_column(String(100))
    condition: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(8), index=True)
    state: Mapped[str] = mapped_column(String(16), index=True)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric())
    value_boolean: Mapped[bool | None]
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    acknowledged_by_username: Mapped[str | None] = mapped_column(String(64))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clear_reason: Mapped[str | None] = mapped_column(String(100))
    revision: Mapped[int] = mapped_column(default=1)


class TelegramDestination(Base):
    __tablename__ = "telegram_destination"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    chat_id: Mapped[str] = mapped_column(String(100))


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("event_id", "kind", name="uq_notification_event_kind"),
        CheckConstraint("status IN ('PENDING','SENDING','SENT','FAILED','SKIPPED')", name="status"),
        CheckConstraint("kind IN ('ACTIVATED','TEST')", name="kind"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("alarm_events.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    chat_id: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), index=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(200))
