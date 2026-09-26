"""alarms_notifications

Revision ID: 0008_alarms
Revises: 0007_automation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_alarms"
down_revision: str | Sequence[str] | None = "0007_automation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_destination",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.String(length=100), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_telegram_destination_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_destination")),
    )
    op.create_table(
        "alarm_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("operator", sa.String(length=2), nullable=False),
        sa.Column("value_numeric", sa.Numeric(), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("for_duration_ms", sa.Integer(), nullable=True),
        sa.Column("hysteresis", sa.Numeric(), nullable=False),
        sa.Column("notification_enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(value_numeric IS NULL OR value_numeric::text NOT IN ('NaN','Infinity','-Infinity')) AND hysteresis::text NOT IN ('NaN','Infinity','-Infinity')",
            name=op.f("ck_alarm_rules_finite"),
        ),
        sa.CheckConstraint(
            "operator IN ('>','>=','<','<=','==','!=')", name=op.f("ck_alarm_rules_operator")
        ),
        sa.CheckConstraint(
            "operator NOT IN ('==','!=') OR hysteresis = 0", name=op.f("ck_alarm_rules_equality")
        ),
        sa.CheckConstraint(
            "severity IN ('INFO','WARNING','CRITICAL')", name=op.f("ck_alarm_rules_severity")
        ),
        sa.CheckConstraint(
            "value_boolean IS NULL OR (operator IN ('==','!=') AND hysteresis = 0)",
            name=op.f("ck_alarm_rules_boolean"),
        ),
        sa.CheckConstraint(
            "(value_numeric IS NOT NULL) != (value_boolean IS NOT NULL)",
            name=op.f("ck_alarm_rules_typed"),
        ),
        sa.CheckConstraint(
            "for_duration_ms IS NULL OR for_duration_ms >= 0", name=op.f("ck_alarm_rules_duration")
        ),
        sa.CheckConstraint("hysteresis >= 0", name=op.f("ck_alarm_rules_hysteresis")),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_alarm_rules_name")),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tags.id"], name=op.f("fk_alarm_rules_tag_id_tags"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alarm_rules")),
    )
    op.create_index(op.f("ix_alarm_rules_enabled"), "alarm_rules", ["enabled"], unique=False)
    op.create_index(op.f("ix_alarm_rules_tag_id"), "alarm_rules", ["tag_id"], unique=False)
    op.create_table(
        "alarm_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tag_name", sa.String(length=200), nullable=False),
        sa.Column("unit", sa.String(length=100), nullable=True),
        sa.Column("condition", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("value_numeric", sa.Numeric(), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clear_reason", sa.String(length=100), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(state = 'CLEARED') = (cleared_at IS NOT NULL)", name=op.f("ck_alarm_events_cleared")
        ),
        sa.CheckConstraint(
            "severity IN ('INFO','WARNING','CRITICAL')", name=op.f("ck_alarm_events_severity")
        ),
        sa.CheckConstraint(
            "state != 'ACKNOWLEDGED' OR acknowledged_at IS NOT NULL",
            name=op.f("ck_alarm_events_acknowledged"),
        ),
        sa.CheckConstraint(
            "state IN ('ACTIVE','ACKNOWLEDGED','CLEARED')", name=op.f("ck_alarm_events_state")
        ),
        sa.CheckConstraint(
            "(value_numeric IS NOT NULL) != (value_boolean IS NOT NULL)",
            name=op.f("ck_alarm_events_typed"),
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["alarm_rules.id"],
            name=op.f("fk_alarm_events_rule_id_alarm_rules"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tags.id"], name=op.f("fk_alarm_events_tag_id_tags"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alarm_events")),
    )
    op.create_index(
        op.f("ix_alarm_events_activated_at"), "alarm_events", ["activated_at"], unique=False
    )
    op.create_index(op.f("ix_alarm_events_rule_id"), "alarm_events", ["rule_id"], unique=False)
    op.create_index(op.f("ix_alarm_events_severity"), "alarm_events", ["severity"], unique=False)
    op.create_index(op.f("ix_alarm_events_state"), "alarm_events", ["state"], unique=False)
    op.create_index(op.f("ix_alarm_events_tag_id"), "alarm_events", ["tag_id"], unique=False)
    op.create_index(
        "uq_alarm_events_open_rule",
        "alarm_events",
        ["rule_id"],
        unique=True,
        postgresql_where=sa.text("state != 'CLEARED'"),
        sqlite_where=sa.text("state != 'CLEARED'"),
    )
    op.create_table(
        "alarm_runtime",
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("true_since", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["alarm_rules.id"],
            name=op.f("fk_alarm_runtime_rule_id_alarm_rules"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("rule_id", name=op.f("pk_alarm_runtime")),
    )
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("chat_id", sa.String(length=100), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.CheckConstraint(
            "kind IN ('ACTIVATED','TEST')", name=op.f("ck_notification_deliveries_kind")
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','SENDING','SENT','FAILED','SKIPPED')",
            name=op.f("ck_notification_deliveries_status"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["alarm_events.id"],
            name=op.f("fk_notification_deliveries_event_id_alarm_events"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_deliveries")),
        sa.UniqueConstraint("event_id", "kind", name="uq_notification_event_kind"),
    )
    op.create_index(
        op.f("ix_notification_deliveries_created_at"),
        "notification_deliveries",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_deliveries_event_id"),
        "notification_deliveries",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_deliveries_status"),
        "notification_deliveries",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_deliveries_status"), table_name="notification_deliveries")
    op.drop_index(op.f("ix_notification_deliveries_event_id"), table_name="notification_deliveries")
    op.drop_index(
        op.f("ix_notification_deliveries_created_at"), table_name="notification_deliveries"
    )
    op.drop_table("notification_deliveries")
    op.drop_table("alarm_runtime")
    op.drop_index(
        "uq_alarm_events_open_rule",
        table_name="alarm_events",
        postgresql_where=sa.text("state != 'CLEARED'"),
        sqlite_where=sa.text("state != 'CLEARED'"),
    )
    op.drop_index(op.f("ix_alarm_events_tag_id"), table_name="alarm_events")
    op.drop_index(op.f("ix_alarm_events_state"), table_name="alarm_events")
    op.drop_index(op.f("ix_alarm_events_severity"), table_name="alarm_events")
    op.drop_index(op.f("ix_alarm_events_rule_id"), table_name="alarm_events")
    op.drop_index(op.f("ix_alarm_events_activated_at"), table_name="alarm_events")
    op.drop_table("alarm_events")
    op.drop_index(op.f("ix_alarm_rules_tag_id"), table_name="alarm_rules")
    op.drop_index(op.f("ix_alarm_rules_enabled"), table_name="alarm_rules")
    op.drop_table("alarm_rules")
    op.drop_table("telegram_destination")
