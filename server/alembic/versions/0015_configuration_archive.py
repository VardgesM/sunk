"""Retain deleted configuration identities without blocking operational deletion."""

import sqlalchemy as sa

from alembic import op

revision = "0015_configuration_archive"
down_revision = "0014_backups"
branch_labels = None
depends_on = None

TABLES = ("locations", "connections", "devices", "tags", "automation_rules", "alarm_rules")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index(f"ix_{table}_archived_at", table, ["archived_at"])
        if table != "locations":
            op.create_check_constraint(
                "archived_disabled", table, "archived_at IS NULL OR NOT enabled"
            )
        # Existing Cloud tombstones are already deleted at their authoritative Edge.
        enabled = ", enabled=false" if table != "locations" else ""
        op.execute(
            sa.text(f"""UPDATE {table} SET archived_at=now(){enabled}
            WHERE id IN (SELECT cloud_id FROM sync_mappings
                         WHERE entity='{table}' AND deleted AND cloud_id IS NOT NULL)""")
        )
    op.drop_constraint("uq_tags_key", "tags", type_="unique")
    op.create_index(
        "uq_tags_key", "tags", ["key"], unique=True, postgresql_where=sa.text("archived_at IS NULL")
    )
    op.drop_constraint("uq_devices_connection_slave", "devices", type_="unique")
    op.create_index(
        "uq_devices_connection_slave",
        "devices",
        ["connection_id", "slave_id"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )


def downgrade() -> None:
    # Never erase retained identities to force an older schema to accept reused keys.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT key FROM tags GROUP BY key HAVING count(*) > 1)
        OR EXISTS (SELECT connection_id, slave_id FROM devices
                   GROUP BY connection_id, slave_id HAVING count(*) > 1) THEN
            RAISE EXCEPTION 'Cannot downgrade: archived identifiers have been reused. Use controlled backup recovery.';
        END IF;
    END $$;""")
    op.drop_index("uq_devices_connection_slave", table_name="devices")
    op.create_unique_constraint(
        "uq_devices_connection_slave", "devices", ["connection_id", "slave_id"]
    )
    op.drop_index("uq_tags_key", table_name="tags")
    op.create_unique_constraint("uq_tags_key", "tags", ["key"])
    for table in reversed(TABLES):
        if table != "locations":
            op.drop_constraint(op.f(f"ck_{table}_archived_disabled"), table, type_="check")
        op.drop_index(f"ix_{table}_archived_at", table_name=table)
        op.drop_column(table, "archived_at")
