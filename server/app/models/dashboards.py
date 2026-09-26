"""Dashboard configuration only; values and control remain in existing services."""

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.configuration import Timestamps


class Dashboard(Timestamps, Base):
    __tablename__ = "dashboards"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        Index(
            "uq_dashboards_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class DashboardWidget(Timestamps, Base):
    __tablename__ = "dashboard_widgets"
    __table_args__ = (
        CheckConstraint(
            "type IN ('value','gauge','chart','boolean','switch','setpoint','alarms','text')",
            name="type",
        ),
        CheckConstraint("length(trim(title)) > 0", name="title_not_blank"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    dashboard_id: Mapped[int] = mapped_column(
        ForeignKey("dashboards.id", ondelete="RESTRICT"), index=True
    )
    type: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    configuration: Mapped[dict] = mapped_column(JSON)


class DashboardWidgetTag(Base):
    __tablename__ = "dashboard_widget_tags"
    widget_id: Mapped[int] = mapped_column(
        ForeignKey("dashboard_widgets.id", ondelete="RESTRICT"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer)


class DashboardWidgetLayout(Base):
    __tablename__ = "dashboard_widget_layouts"
    __table_args__ = (
        CheckConstraint("breakpoint IN ('lg','md','sm')", name="breakpoint"),
        CheckConstraint(
            "x >= 0 AND y >= 0 AND y <= 10000 AND w >= 1 AND h BETWEEN 2 AND 40", name="bounds"
        ),
        CheckConstraint(
            "(breakpoint = 'lg' AND x + w <= 12) OR (breakpoint = 'md' AND x + w <= 6) OR (breakpoint = 'sm' AND x = 0 AND w = 1)",
            name="columns",
        ),
    )
    widget_id: Mapped[int] = mapped_column(
        ForeignKey("dashboard_widgets.id", ondelete="RESTRICT"), primary_key=True
    )
    breakpoint: Mapped[str] = mapped_column(String(2), primary_key=True)
    x: Mapped[int] = mapped_column(Integer)
    y: Mapped[int] = mapped_column(Integer)
    w: Mapped[int] = mapped_column(Integer)
    h: Mapped[int] = mapped_column(Integer)
