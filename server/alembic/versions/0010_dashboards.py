"""Relational dashboards, widget bindings and responsive layouts."""

import sqlalchemy as sa
from alembic import op

revision = "0010_dashboards"
down_revision = "0009_serial_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
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
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_dashboards_name_not_blank")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dashboards")),
        sa.UniqueConstraint("slug", name=op.f("uq_dashboards_slug")),
    )
    op.create_index(
        "uq_dashboards_default",
        "dashboards",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default"),
    )
    op.create_table(
        "dashboard_widgets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dashboard_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
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
            "type IN ('value','gauge','chart','boolean','switch','setpoint','alarms','text')",
            name=op.f("ck_dashboard_widgets_type"),
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0", name=op.f("ck_dashboard_widgets_title_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["dashboard_id"],
            ["dashboards.id"],
            name=op.f("fk_dashboard_widgets_dashboard_id_dashboards"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dashboard_widgets")),
    )
    op.create_index(
        op.f("ix_dashboard_widgets_dashboard_id"),
        "dashboard_widgets",
        ["dashboard_id"],
        unique=False,
    )
    op.create_table(
        "dashboard_widget_tags",
        sa.Column("widget_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.id"],
            name=op.f("fk_dashboard_widget_tags_tag_id_tags"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["widget_id"],
            ["dashboard_widgets.id"],
            name=op.f("fk_dashboard_widget_tags_widget_id_dashboard_widgets"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("widget_id", "tag_id", name=op.f("pk_dashboard_widget_tags")),
    )
    op.create_index(
        op.f("ix_dashboard_widget_tags_tag_id"), "dashboard_widget_tags", ["tag_id"], unique=False
    )
    op.create_table(
        "dashboard_widget_layouts",
        sa.Column("widget_id", sa.Integer(), nullable=False),
        sa.Column("breakpoint", sa.String(length=2), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("w", sa.Integer(), nullable=False),
        sa.Column("h", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(breakpoint = 'lg' AND x + w <= 12) OR (breakpoint = 'md' AND x + w <= 6) OR (breakpoint = 'sm' AND x = 0 AND w = 1)",
            name=op.f("ck_dashboard_widget_layouts_columns"),
        ),
        sa.CheckConstraint(
            "breakpoint IN ('lg','md','sm')", name=op.f("ck_dashboard_widget_layouts_breakpoint")
        ),
        sa.CheckConstraint(
            "x >= 0 AND y >= 0 AND y <= 10000 AND w >= 1 AND h BETWEEN 2 AND 40",
            name=op.f("ck_dashboard_widget_layouts_bounds"),
        ),
        sa.ForeignKeyConstraint(
            ["widget_id"],
            ["dashboard_widgets.id"],
            name=op.f("fk_dashboard_widget_layouts_widget_id_dashboard_widgets"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "widget_id", "breakpoint", name=op.f("pk_dashboard_widget_layouts")
        ),
    )


def downgrade() -> None:
    op.drop_table("dashboard_widget_layouts")
    op.drop_table("dashboard_widget_tags")
    op.drop_table("dashboard_widgets")
    op.drop_table("dashboards")
