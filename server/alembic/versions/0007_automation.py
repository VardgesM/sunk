"""Persistent automation rules, runtime and command-linked executions."""

import sqlalchemy as sa
from alembic import op

revision = "0007_automation"
down_revision = "0006_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("condition_mode", sa.String(length=3), nullable=False),
        sa.Column("for_duration_ms", sa.Integer(), nullable=True),
        sa.Column("cooldown_ms", sa.Integer(), nullable=True),
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
            "condition_mode IN ('ALL','ANY')", name=op.f("ck_automation_rules_mode")
        ),
        sa.CheckConstraint(
            "cooldown_ms IS NULL OR cooldown_ms >= 0", name=op.f("ck_automation_rules_cooldown")
        ),
        sa.CheckConstraint(
            "for_duration_ms IS NULL OR for_duration_ms >= 0",
            name=op.f("ck_automation_rules_duration"),
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_automation_rules_name")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_rules")),
    )
    op.create_index(
        op.f("ix_automation_rules_enabled"), "automation_rules", ["enabled"], unique=False
    )
    op.create_table(
        "automation_conditions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("operator", sa.String(length=2), nullable=False),
        sa.Column("value_numeric", sa.Numeric(), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        sa.Column("hysteresis", sa.Numeric(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(value_numeric IS NULL OR value_numeric::text NOT IN ('NaN','Infinity','-Infinity')) AND hysteresis::text NOT IN ('NaN','Infinity','-Infinity')",
            name=op.f("ck_automation_conditions_finite"),
        ),
        sa.CheckConstraint(
            "operator IN ('>','>=','<','<=','==','!=')",
            name=op.f("ck_automation_conditions_operator"),
        ),
        sa.CheckConstraint(
            "operator NOT IN ('==','!=') OR hysteresis = 0",
            name=op.f("ck_automation_conditions_equality"),
        ),
        sa.CheckConstraint(
            "value_boolean IS NULL OR (operator IN ('==','!=') AND hysteresis = 0)",
            name=op.f("ck_automation_conditions_boolean"),
        ),
        sa.CheckConstraint(
            "(value_numeric IS NOT NULL) != (value_boolean IS NOT NULL)",
            name=op.f("ck_automation_conditions_typed"),
        ),
        sa.CheckConstraint("hysteresis >= 0", name=op.f("ck_automation_conditions_hysteresis")),
        sa.CheckConstraint("sort_order >= 0", name=op.f("ck_automation_conditions_sort_order")),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["automation_rules.id"],
            name=op.f("fk_automation_conditions_rule_id_automation_rules"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.id"],
            name=op.f("fk_automation_conditions_tag_id_tags"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_conditions")),
    )
    op.create_index(
        op.f("ix_automation_conditions_rule_id"), "automation_conditions", ["rule_id"], unique=False
    )
    op.create_index(
        op.f("ix_automation_conditions_tag_id"), "automation_conditions", ["tag_id"], unique=False
    )
    op.create_table(
        "automation_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("target_tag_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("value_numeric", sa.Numeric(), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("kind = 'SET_TAG_VALUE'", name=op.f("ck_automation_actions_kind")),
        sa.CheckConstraint(
            "value_numeric IS NULL OR value_numeric::text NOT IN ('NaN','Infinity','-Infinity')",
            name=op.f("ck_automation_actions_finite"),
        ),
        sa.CheckConstraint(
            "(value_numeric IS NOT NULL) != (value_boolean IS NOT NULL)",
            name=op.f("ck_automation_actions_typed"),
        ),
        sa.CheckConstraint("sort_order >= 0", name=op.f("ck_automation_actions_sort_order")),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["automation_rules.id"],
            name=op.f("fk_automation_actions_rule_id_automation_rules"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_tag_id"],
            ["tags.id"],
            name=op.f("fk_automation_actions_target_tag_id_tags"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_actions")),
    )
    op.create_index(
        op.f("ix_automation_actions_rule_id"), "automation_actions", ["rule_id"], unique=False
    )
    op.create_index(
        op.f("ix_automation_actions_target_tag_id"),
        "automation_actions",
        ["target_tag_id"],
        unique=False,
    )
    op.create_table(
        "automation_runtime",
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("condition_state", sa.Boolean(), nullable=False),
        sa.Column("armed", sa.Boolean(), nullable=False),
        sa.Column("latches", sa.JSON(), nullable=False),
        sa.Column("true_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_result", sa.String(length=24), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "state IN ('IDLE','WAITING_FOR_DURATION','ACTIVE','COOLDOWN','DISABLED','ERROR')",
            name=op.f("ck_automation_runtime_state"),
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["automation_rules.id"],
            name=op.f("fk_automation_runtime_rule_id_automation_rules"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("rule_id", name=op.f("pk_automation_runtime")),
    )
    op.create_table(
        "automation_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("rule_version", sa.DateTime(timezone=True), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("result", sa.String(length=24), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "result IN ('COMMANDS_CREATED','SUCCESS','PARTIAL_FAILURE','FAILED','SKIPPED')",
            name=op.f("ck_automation_executions_result"),
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["automation_rules.id"],
            name=op.f("fk_automation_executions_rule_id_automation_rules"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_executions")),
    )
    op.create_index(
        op.f("ix_automation_executions_result"), "automation_executions", ["result"], unique=False
    )
    op.create_index(
        op.f("ix_automation_executions_rule_id"), "automation_executions", ["rule_id"], unique=False
    )
    op.create_index(
        op.f("ix_automation_executions_triggered_at"),
        "automation_executions",
        ["triggered_at"],
        unique=False,
    )
    op.create_table(
        "automation_execution_commands",
        sa.Column("execution_id", sa.Integer(), nullable=False),
        sa.Column("command_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["command_id"],
            ["commands.id"],
            name=op.f("fk_automation_execution_commands_command_id_commands"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["automation_executions.id"],
            name=op.f("fk_automation_execution_commands_execution_id_automation_executions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "execution_id", "command_id", name=op.f("pk_automation_execution_commands")
        ),
        sa.UniqueConstraint("command_id", name=op.f("uq_automation_execution_commands_command_id")),
    )


def downgrade() -> None:
    op.drop_table("automation_execution_commands")
    op.drop_table("automation_executions")
    op.drop_table("automation_runtime")
    op.drop_table("automation_actions")
    op.drop_table("automation_conditions")
    op.drop_table("automation_rules")
