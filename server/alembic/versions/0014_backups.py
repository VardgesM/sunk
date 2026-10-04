"""Portable configuration identity and post-restore synchronization safety fence."""

import sqlalchemy as sa
from alembic import op

revision = "0014_backups"
down_revision = "0013_realtime_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "configuration_identities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity", sa.String(40), nullable=False),
        sa.Column("local_id", sa.Integer(), nullable=False),
        sa.UniqueConstraint("entity", "local_id"),
    )
    op.create_table(
        "recovery_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("backup_id", sa.String(36), nullable=False),
        sa.Column("sync_review_required", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("recovery_state")
    op.drop_table("configuration_identities")
