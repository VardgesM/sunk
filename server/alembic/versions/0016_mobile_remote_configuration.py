"""Durable mobile login and acknowledged remote configuration requests."""

import sqlalchemy as sa
from alembic import op

revision = "0016_mobile_remote_configuration"
down_revision = "0015_configuration_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("auth_sessions", "expires_at", nullable=True)
    op.add_column(
        "edge_installations",
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default="[]"),
    )
    for table in ("remote_requests", "remote_inbox"):
        op.add_column(table, sa.Column("result", sa.JSON(), nullable=True))
    op.drop_constraint(op.f("ck_remote_requests_kind"), "remote_requests", type_="check")
    op.create_check_constraint(
        "kind", "remote_requests", "kind IN ('command','acknowledge','configuration')"
    )


def downgrade() -> None:
    # Do not discard durable requests to force an older release to accept the database.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM remote_requests WHERE kind='configuration')
        OR EXISTS (SELECT 1 FROM remote_inbox WHERE kind='configuration') THEN
            RAISE EXCEPTION 'Remote configuration records exist; use controlled backup recovery';
        END IF;
    END $$""")
    op.execute("UPDATE auth_sessions SET expires_at=now() WHERE expires_at IS NULL")
    op.alter_column("auth_sessions", "expires_at", nullable=False)
    op.drop_constraint(op.f("ck_remote_requests_kind"), "remote_requests", type_="check")
    op.create_check_constraint("kind", "remote_requests", "kind IN ('command','acknowledge')")
    for table in ("remote_inbox", "remote_requests"):
        op.drop_column(table, "result")
    op.drop_column("edge_installations", "capabilities")
