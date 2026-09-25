"""Typed history and per-tag storage policies."""

import sqlalchemy as sa
from alembic import op

revision = "0004_history"
down_revision = "0003_current_values"
branch_labels = None
depends_on = None

POLICY_CHECKS = {
    "history_mode": "history_mode IN ('every_sample','fixed_interval','on_change')",
    "history_interval": "history_interval_ms IS NULL OR history_interval_ms > 0",
    "history_threshold": "history_change_threshold IS NULL OR history_change_threshold >= 0",
    "history_retention": "history_retention_days IS NULL OR history_retention_days > 0",
    "history_fixed": "history_mode <> 'fixed_interval' OR (history_interval_ms IS NOT NULL AND history_interval_ms >= poll_interval_ms)",
    "history_change": "history_mode <> 'on_change' OR data_type = 'bool' OR history_change_threshold IS NOT NULL",
    "history_finite": "history_change_threshold IS NULL OR history_change_threshold < 'Infinity'::float8",
}


def upgrade() -> None:
    op.add_column(
        "tags",
        sa.Column("history_mode", sa.String(20), server_default="every_sample", nullable=False),
    )
    op.add_column("tags", sa.Column("history_interval_ms", sa.Integer(), nullable=True))
    op.add_column("tags", sa.Column("history_change_threshold", sa.Float(), nullable=True))
    op.add_column("tags", sa.Column("history_retention_days", sa.Integer(), nullable=True))
    for name, condition in POLICY_CHECKS.items():
        op.create_check_constraint(op.f(f"ck_tags_{name}"), "tags", condition)
    op.create_table(
        "tag_history",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("value_numeric", sa.Numeric(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        sa.Column("quality", sa.String(12), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "quality IN ('GOOD','STALE','BAD','COMM_ERROR','DISABLED')",
            name=op.f("ck_tag_history_quality"),
        ),
        sa.CheckConstraint(
            "(CASE WHEN value_numeric IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN value_boolean IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN value_text IS NOT NULL THEN 1 ELSE 0 END) = CASE WHEN quality = 'GOOD' THEN 1 ELSE 0 END",
            name=op.f("ck_tag_history_typed_quality"),
        ),
        sa.CheckConstraint(
            "quality <> 'GOOD' OR source_timestamp IS NOT NULL",
            name=op.f("ck_tag_history_source_required"),
        ),
        sa.CheckConstraint(
            "value_numeric IS NULL OR (value_numeric > '-Infinity'::numeric AND value_numeric < 'Infinity'::numeric)",
            name=op.f("ck_tag_history_finite_numeric"),
        ),
    )
    op.create_index("ix_tag_history_tag_id", "tag_history", ["tag_id"])
    op.create_index("ix_tag_history_recorded_at", "tag_history", ["recorded_at"])
    op.create_index("ix_tag_history_tag_recorded", "tag_history", ["tag_id", "recorded_at", "id"])


def downgrade() -> None:
    op.drop_table("tag_history")
    for name in reversed(POLICY_CHECKS):
        op.drop_constraint(op.f(f"ck_tags_{name}"), "tags", type_="check")
    for name in (
        "history_retention_days",
        "history_change_threshold",
        "history_interval_ms",
        "history_mode",
    ):
        op.drop_column("tags", name)
