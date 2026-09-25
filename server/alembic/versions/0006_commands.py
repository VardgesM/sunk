"""Persistent verified command pipeline, disabled by default for physical writes."""

import sqlalchemy as sa
from alembic import op

revision = "0006_commands"
down_revision = "0005_modbus_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "worker_runtime",
        sa.Column("writes_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "commands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column(
            "tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="RESTRICT"), nullable=False
        ),
        *[
            sa.Column(prefix + suffix, kind, nullable=True)
            for prefix in ("requested", "previous", "verified")
            for suffix, kind in (("_numeric", sa.Numeric()), ("_boolean", sa.Boolean()))
        ],
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("telemetry_mode", sa.String(16), nullable=False),
        sa.Column("physical_confirmed", sa.Boolean(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        *[
            sa.Column(name, sa.DateTime(timezone=True), nullable=False)
            for name in (
                "created_at",
                "expires_at",
                "tag_version",
                "device_version",
                "connection_version",
            )
        ],
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.UniqueConstraint("request_id", name=op.f("uq_commands_request_id")),
        sa.CheckConstraint(
            "status IN ('QUEUED','EXECUTING','VERIFYING','SUCCESS','FAILED','CANCELLED','EXPIRED')",
            name=op.f("ck_commands_status"),
        ),
        sa.CheckConstraint(
            "source IN ('manual','automation','system')", name=op.f("ck_commands_source")
        ),
        sa.CheckConstraint(
            "telemetry_mode IN ('simulator','modbus')", name=op.f("ck_commands_mode")
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND revision > 0", name=op.f("ck_commands_counters")
        ),
        sa.CheckConstraint(
            "(requested_numeric IS NOT NULL) != (requested_boolean IS NOT NULL)",
            name=op.f("ck_commands_requested_type"),
        ),
        sa.CheckConstraint(
            "previous_numeric IS NULL OR previous_boolean IS NULL",
            name=op.f("ck_commands_previous_type"),
        ),
        sa.CheckConstraint(
            "verified_numeric IS NULL OR verified_boolean IS NULL",
            name=op.f("ck_commands_verified_type"),
        ),
        sa.CheckConstraint(
            "status != 'SUCCESS' OR verified_numeric IS NOT NULL OR verified_boolean IS NOT NULL",
            name=op.f("ck_commands_success_value"),
        ),
        sa.CheckConstraint(
            "(status IN ('SUCCESS','FAILED','CANCELLED','EXPIRED')) = (completed_at IS NOT NULL)",
            name=op.f("ck_commands_completion"),
        ),
        sa.CheckConstraint(
            " AND ".join(
                f"({p}_numeric IS NULL OR {p}_numeric::text NOT IN ('NaN','Infinity','-Infinity'))"
                for p in ("requested", "previous", "verified")
            ),
            name=op.f("ck_commands_finite"),
        ),
    )
    op.create_index("ix_commands_status_created_at", "commands", ["status", "created_at"])
    op.create_index("ix_commands_tag_created_at", "commands", ["tag_id", "created_at"])
    op.create_index("ix_commands_created_at", "commands", ["created_at"])


def downgrade() -> None:
    op.drop_table("commands")
    op.drop_column("worker_runtime", "writes_enabled")
