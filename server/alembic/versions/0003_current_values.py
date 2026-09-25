"""Persist latest typed tag values and quality; no history."""

import sqlalchemy as sa
from alembic import op

revision = "0003_current_values"
down_revision = "0002_configuration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tag_current_values",
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("value_numeric", sa.Numeric(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("quality", sa.String(12), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("revision", sa.BigInteger(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("tag_id", name=op.f("pk_tag_current_values")),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.id"],
            ondelete="RESTRICT",
            name=op.f("fk_tag_current_values_tag_id_tags"),
        ),
        sa.CheckConstraint(
            "quality IN ('GOOD','STALE','BAD','COMM_ERROR','DISABLED')",
            name=op.f("ck_tag_current_values_quality"),
        ),
        sa.CheckConstraint(
            "(CASE WHEN value_numeric IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN value_text IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN value_boolean IS NOT NULL THEN 1 ELSE 0 END) <= 1",
            name=op.f("ck_tag_current_values_one_value_type"),
        ),
        sa.CheckConstraint(
            "quality <> 'GOOD' OR ((value_numeric IS NOT NULL OR value_text IS NOT NULL "
            "OR value_boolean IS NOT NULL) AND source_timestamp IS NOT NULL AND error IS NULL)",
            name=op.f("ck_tag_current_values_good_has_value"),
        ),
        sa.CheckConstraint("revision > 0", name=op.f("ck_tag_current_values_revision_positive")),
        sa.CheckConstraint(
            "value_numeric IS NULL OR (value_numeric > '-Infinity'::numeric "
            "AND value_numeric < 'Infinity'::numeric)",
            name=op.f("ck_tag_current_values_finite_numeric"),
        ),
    )
    op.create_index("ix_tag_current_values_quality", "tag_current_values", ["quality"])


def downgrade() -> None:
    op.drop_table("tag_current_values")
