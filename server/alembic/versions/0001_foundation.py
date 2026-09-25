"""Establish migration history without introducing business tables."""

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass  # Intentionally empty: only Alembic's version table is needed.


def downgrade() -> None:
    pass
