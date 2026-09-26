from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.configuration import Timestamps


class AutomationRule(Timestamps, Base):
    __tablename__ = "automation_rules"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="name"),
        CheckConstraint("condition_mode IN ('ALL','ANY')", name="mode"),
        CheckConstraint("for_duration_ms IS NULL OR for_duration_ms >= 0", name="duration"),
        CheckConstraint("cooldown_ms IS NULL OR cooldown_ms >= 0", name="cooldown"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=False, index=True)
    priority: Mapped[int] = mapped_column(default=0)
    condition_mode: Mapped[str] = mapped_column(String(3), default="ALL")
    for_duration_ms: Mapped[int | None]
    cooldown_ms: Mapped[int | None]


class AutomationCondition(Base):
    __tablename__ = "automation_conditions"
    __table_args__ = (
        CheckConstraint("operator IN ('>','>=','<','<=','==','!=')", name="operator"),
        CheckConstraint("(value_numeric IS NOT NULL) != (value_boolean IS NOT NULL)", name="typed"),
        CheckConstraint("hysteresis >= 0", name="hysteresis"),
        CheckConstraint("sort_order >= 0", name="sort_order"),
        CheckConstraint(
            "(value_numeric IS NULL OR value_numeric::text NOT IN ('NaN','Infinity','-Infinity')) AND hysteresis::text NOT IN ('NaN','Infinity','-Infinity')",
            name="finite",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "value_boolean IS NULL OR (operator IN ('==','!=') AND hysteresis = 0)", name="boolean"
        ),
        CheckConstraint("operator NOT IN ('==','!=') OR hysteresis = 0", name="equality"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="RESTRICT"), index=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="RESTRICT"), index=True)
    operator: Mapped[str] = mapped_column(String(2))
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric())
    value_boolean: Mapped[bool | None]
    hysteresis: Mapped[Decimal] = mapped_column(Numeric(), default=0)
    sort_order: Mapped[int] = mapped_column(default=0)


class AutomationAction(Base):
    __tablename__ = "automation_actions"
    __table_args__ = (
        CheckConstraint("kind = 'SET_TAG_VALUE'", name="kind"),
        CheckConstraint("sort_order >= 0", name="sort_order"),
        CheckConstraint(
            "value_numeric IS NULL OR value_numeric::text NOT IN ('NaN','Infinity','-Infinity')",
            name="finite",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint("(value_numeric IS NOT NULL) != (value_boolean IS NOT NULL)", name="typed"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="RESTRICT"), index=True
    )
    target_tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), default="SET_TAG_VALUE")
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric())
    value_boolean: Mapped[bool | None]
    sort_order: Mapped[int] = mapped_column(default=0)


class AutomationRuntime(Base):
    __tablename__ = "automation_runtime"
    __table_args__ = (
        CheckConstraint(
            "state IN ('IDLE','WAITING_FOR_DURATION','ACTIVE','COOLDOWN','DISABLED','ERROR')",
            name="state",
        ),
    )
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="RESTRICT"), primary_key=True
    )
    state: Mapped[str] = mapped_column(String(24), default="IDLE")
    condition_state: Mapped[bool] = mapped_column(default=False)
    armed: Mapped[bool] = mapped_column(default=True)
    latches: Mapped[dict] = mapped_column(JSON, default=dict)
    true_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[str | None] = mapped_column(String(24))
    error: Mapped[str | None] = mapped_column(Text)


class AutomationExecution(Base):
    __tablename__ = "automation_executions"
    __table_args__ = (
        CheckConstraint(
            "result IN ('COMMANDS_CREATED','SUCCESS','PARTIAL_FAILURE','FAILED','SKIPPED')",
            name="result",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="RESTRICT"), index=True
    )
    rule_version: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[list] = mapped_column(JSON)
    result: Mapped[str] = mapped_column(String(24), index=True)
    error: Mapped[str | None] = mapped_column(Text)


class AutomationExecutionCommand(Base):
    __tablename__ = "automation_execution_commands"
    execution_id: Mapped[int] = mapped_column(
        ForeignKey("automation_executions.id", ondelete="RESTRICT"), primary_key=True
    )
    command_id: Mapped[int] = mapped_column(
        ForeignKey("commands.id", ondelete="RESTRICT"), primary_key=True, unique=True
    )
