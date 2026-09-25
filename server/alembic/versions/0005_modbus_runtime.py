"""Read-only Modbus runtime state, worker discovery, and current-value provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0005_modbus_runtime"
down_revision = "0004_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tag_history", sa.Column("source", sa.String(16), nullable=True))
    op.create_check_constraint(
        op.f("ck_tag_history_source"),
        "tag_history",
        "source IS NULL OR source IN ('simulator','modbus_rtu','modbus_tcp')",
    )
    op.add_column("tag_current_values", sa.Column("source", sa.String(16), nullable=True))
    op.create_check_constraint(
        op.f("ck_tag_current_values_source"),
        "tag_current_values",
        "source IS NULL OR source IN ('simulator','modbus_rtu','modbus_tcp')",
    )
    op.create_table(
        "worker_runtime",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("serial_ports", sa.JSON(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovery_error", sa.Text(), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_worker_runtime_singleton")),
        sa.CheckConstraint(
            "mode IN ('disabled','simulator','modbus')", name=op.f("ck_worker_runtime_mode")
        ),
    )
    op.create_table(
        "connection_runtime",
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("connections.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("state", sa.String(16), server_default="DISCONNECTED", nullable=False),
        sa.Column("configuration_version", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("test_id", sa.String(36), nullable=True),
        sa.Column("test_completed_id", sa.String(36), nullable=True),
        sa.Column("test_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("test_configuration_version", sa.DateTime(timezone=True), nullable=True),
        sa.Column("test_success", sa.Boolean(), nullable=True),
        sa.Column("test_message", sa.Text(), nullable=True),
        sa.Column("test_latency_ms", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "state IN ('CONNECTED','DISCONNECTED','CONNECTING','ERROR','DISABLED')",
            name=op.f("ck_connection_runtime_state"),
        ),
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_tag_history_source"), "tag_history", type_="check")
    op.drop_column("tag_history", "source")
    op.drop_table("connection_runtime")
    op.drop_table("worker_runtime")
    op.drop_constraint(op.f("ck_tag_current_values_source"), "tag_current_values", type_="check")
    op.drop_column("tag_current_values", "source")
