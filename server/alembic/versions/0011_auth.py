"""Local authentication, audit and human action attribution."""

import sqlalchemy as sa
from alembic import op

revision = "0011_auth"
down_revision = "0010_dashboards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("role IN ('ADMIN','OPERATOR','VIEWER')", name=op.f("ck_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_auth_sessions")),
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_auth_sessions_expires_at"), "auth_sessions", ["expires_at"], unique=False
    )
    op.create_table(
        "login_limits",
        sa.Column("bucket", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("bucket", name=op.f("pk_login_limits")),
    )
    op.create_index(
        op.f("ix_login_limits_started_at"), "login_limits", ["started_at"], unique=False
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_audit_log_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"], unique=False)
    op.create_index(
        "ix_audit_log_user_timestamp", "audit_log", ["user_id", "timestamp"], unique=False
    )
    op.create_index(op.f("ix_audit_log_timestamp"), "audit_log", ["timestamp"], unique=False)
    op.add_column("commands", sa.Column("requested_by", sa.Integer(), nullable=True))
    op.add_column("commands", sa.Column("requested_by_username", sa.String(64), nullable=True))
    op.create_foreign_key(
        op.f("fk_commands_requested_by_users"),
        "commands",
        "users",
        ["requested_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_commands_requested_by", "commands", ["requested_by"])
    op.add_column("alarm_events", sa.Column("acknowledged_by", sa.Integer(), nullable=True))
    op.add_column(
        "alarm_events", sa.Column("acknowledged_by_username", sa.String(64), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_alarm_events_acknowledged_by_users"),
        "alarm_events",
        "users",
        ["acknowledged_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_alarm_events_acknowledged_by", "alarm_events", ["acknowledged_by"])


def downgrade() -> None:
    op.drop_index("ix_commands_requested_by", table_name="commands")
    op.drop_constraint(op.f("fk_commands_requested_by_users"), "commands", type_="foreignkey")
    op.drop_column("commands", "requested_by_username")
    op.drop_column("commands", "requested_by")
    op.drop_index("ix_alarm_events_acknowledged_by", table_name="alarm_events")
    op.drop_constraint(
        op.f("fk_alarm_events_acknowledged_by_users"), "alarm_events", type_="foreignkey"
    )
    op.drop_column("alarm_events", "acknowledged_by_username")
    op.drop_column("alarm_events", "acknowledged_by")
    op.drop_table("audit_log")
    op.drop_table("login_limits")
    op.drop_table("auth_sessions")
    op.drop_table("users")
