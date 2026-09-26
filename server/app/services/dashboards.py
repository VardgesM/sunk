from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dashboard, DashboardWidget, DashboardWidgetLayout, DashboardWidgetTag, Tag
from app.schemas.dashboards import (
    DashboardDetail,
    DashboardRead,
    LayoutInput,
    WidgetInput,
    WidgetRead,
)


async def lock_configuration(session: AsyncSession) -> None:
    # Serializes default changes and child edits, including creation of the first dashboard.
    if session.bind.dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(927009)"))


async def require_dashboard(session: AsyncSession, identifier: int) -> Dashboard:
    row = await session.get(Dashboard, identifier)
    if row is None:
        raise HTTPException(404, "Dashboard not found")
    return row


def touch(row: Dashboard) -> None:
    row.revision += 1
    row.updated_at = datetime.now(UTC)


async def widget_reads(session: AsyncSession, dashboard_id: int) -> list[WidgetRead]:
    widgets = list(
        await session.scalars(
            select(DashboardWidget)
            .where(DashboardWidget.dashboard_id == dashboard_id)
            .order_by(DashboardWidget.id)
        )
    )
    ids = [w.id for w in widgets]
    bindings = list(
        await session.scalars(
            select(DashboardWidgetTag)
            .where(DashboardWidgetTag.widget_id.in_(ids))
            .order_by(DashboardWidgetTag.sort_order)
        )
    )
    layouts = list(
        await session.scalars(
            select(DashboardWidgetLayout).where(DashboardWidgetLayout.widget_id.in_(ids))
        )
    )
    return [
        WidgetRead(
            id=w.id,
            dashboard_id=w.dashboard_id,
            type=w.type,
            title=w.title,
            configuration=w.configuration,
            created_at=w.created_at,
            updated_at=w.updated_at,
            tag_ids=[b.tag_id for b in bindings if b.widget_id == w.id],
            layouts=[
                LayoutInput.model_validate(
                    {key: getattr(layout, key) for key in ("breakpoint", "x", "y", "w", "h")}
                )
                for layout in layouts
                if layout.widget_id == w.id
            ],
        )
        for w in widgets
    ]


async def detail(session: AsyncSession, row: Dashboard) -> DashboardDetail:
    return DashboardDetail(
        **DashboardRead.model_validate(row).model_dump(),
        widgets=await widget_reads(session, row.id),
    )


async def validate_tags(session: AsyncSession, payload: WidgetInput) -> None:
    tags = list(
        await session.scalars(select(Tag).where(Tag.id.in_(payload.tag_ids)).with_for_update())
    )
    if len(tags) != len(payload.tag_ids):
        raise HTTPException(422, "One or more Tags do not exist")
    for tag in tags:
        numeric = tag.data_type != "bool"
        if payload.type in ("gauge", "chart", "setpoint") and not numeric:
            raise HTTPException(422, "This widget requires numeric Tags")
        if payload.type in ("boolean", "switch") and numeric:
            raise HTTPException(422, "This widget requires boolean Tags")
        if payload.type in ("switch", "setpoint"):
            register = "coil" if payload.type == "switch" else "holding_register"
            if not tag.enabled or not tag.writable or tag.register_type != register:
                raise HTTPException(
                    422, "Control requires an enabled, writable Tag of the supported register type"
                )
    if payload.type == "chart" and len({tag.unit or "" for tag in tags}) > 1:
        raise HTTPException(
            422, "Chart Tags must have the same unit; use separate charts for incompatible units"
        )


async def replace_children(
    session: AsyncSession, widget: DashboardWidget, payload: WidgetInput
) -> None:
    await session.execute(
        delete(DashboardWidgetTag).where(DashboardWidgetTag.widget_id == widget.id)
    )
    await session.execute(
        delete(DashboardWidgetLayout).where(DashboardWidgetLayout.widget_id == widget.id)
    )
    session.add_all(
        [
            DashboardWidgetTag(widget_id=widget.id, tag_id=tag_id, sort_order=index)
            for index, tag_id in enumerate(payload.tag_ids)
        ]
    )
    session.add_all(
        [
            DashboardWidgetLayout(widget_id=widget.id, **layout.model_dump())
            for layout in payload.layouts
        ]
    )


async def delete_widgets(session: AsyncSession, ids: list[int]) -> None:
    for model in (DashboardWidgetTag, DashboardWidgetLayout, DashboardWidget):
        key = model.id if model is DashboardWidget else model.widget_id
        await session.execute(delete(model).where(key.in_(ids)))
