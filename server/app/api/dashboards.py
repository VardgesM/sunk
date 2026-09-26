from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Response
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Dashboard, DashboardWidget, DashboardWidgetLayout
from app.schemas.dashboards import (
    DashboardDetail,
    DashboardInput,
    DashboardRead,
    LayoutSave,
    WidgetInput,
    WidgetRead,
)
from app.services.dashboards import (
    delete_widgets,
    detail,
    lock_configuration,
    replace_children,
    require_dashboard,
    touch,
    validate_tags,
    widget_reads,
)

router = APIRouter(prefix="/api", tags=["dashboards"])
Session = Annotated[AsyncSession, Depends(get_session)]
Identifier = Annotated[int, Path(ge=1, le=2147483647)]


async def commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            409, "Dashboard slug already exists or configuration is still referenced"
        ) from None


@router.get("/dashboards", response_model=list[DashboardRead])
async def dashboards(
    session: Session, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)
):
    return list(
        await session.scalars(
            select(Dashboard)
            .order_by(Dashboard.is_default.desc(), Dashboard.id)
            .limit(limit)
            .offset(offset)
        )
    )


@router.post("/dashboards", response_model=DashboardDetail, status_code=201)
async def create(payload: DashboardInput, session: Session):
    await lock_configuration(session)
    if payload.is_default:
        await session.execute(
            update(Dashboard)
            .where(Dashboard.is_default)
            .values(is_default=False, revision=Dashboard.revision + 1)
        )
    row = Dashboard(**payload.model_dump())
    session.add(row)
    await commit(session)
    return await detail(session, row)


@router.get("/dashboards/{identifier}", response_model=DashboardDetail)
async def read(identifier: Identifier, session: Session):
    return await detail(session, await require_dashboard(session, identifier))


@router.patch("/dashboards/{identifier}", response_model=DashboardDetail)
async def patch(identifier: Identifier, session: Session, changes: dict = Body(...)):
    await lock_configuration(session)
    row = await require_dashboard(session, identifier)
    try:
        payload = DashboardInput.model_validate(
            {**{k: getattr(row, k) for k in DashboardInput.model_fields}, **changes}
        )
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(e["msg"] for e in exc.errors())) from None
    if payload.is_default:
        await session.execute(
            update(Dashboard)
            .where(Dashboard.is_default, Dashboard.id != identifier)
            .values(is_default=False, revision=Dashboard.revision + 1)
        )
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    touch(row)
    await commit(session)
    return await detail(session, row)


@router.delete("/dashboards/{identifier}", status_code=204)
async def remove(identifier: Identifier, session: Session):
    await lock_configuration(session)
    row = await require_dashboard(session, identifier)
    ids = list(
        await session.scalars(
            select(DashboardWidget.id).where(DashboardWidget.dashboard_id == identifier)
        )
    )
    await delete_widgets(session, ids)
    await session.delete(row)
    await commit(session)
    return Response(status_code=204)


@router.post("/dashboards/{identifier}/widgets", response_model=WidgetRead, status_code=201)
async def create_widget(identifier: Identifier, payload: WidgetInput, session: Session):
    await lock_configuration(session)
    parent = await require_dashboard(session, identifier)
    count = await session.scalar(
        select(func.count())
        .select_from(DashboardWidget)
        .where(DashboardWidget.dashboard_id == identifier)
    )
    if count >= 100:
        raise HTTPException(422, "A dashboard supports at most 100 widgets")
    await validate_tags(session, payload)
    widget = DashboardWidget(
        dashboard_id=identifier,
        type=payload.type,
        title=payload.title,
        configuration=payload.configuration,
    )
    session.add(widget)
    await session.flush()
    await replace_children(session, widget, payload)
    touch(parent)
    await commit(session)
    return next(w for w in await widget_reads(session, identifier) if w.id == widget.id)


async def require_widget(session: AsyncSession, identifier: int) -> DashboardWidget:
    widget = await session.get(DashboardWidget, identifier)
    if widget is None:
        raise HTTPException(404, "Widget not found")
    return widget


@router.patch("/dashboard-widgets/{identifier}", response_model=WidgetRead)
async def patch_widget(identifier: Identifier, session: Session, changes: dict = Body(...)):
    await lock_configuration(session)
    widget = await require_widget(session, identifier)
    old = next(w for w in await widget_reads(session, widget.dashboard_id) if w.id == identifier)
    try:
        payload = WidgetInput.model_validate(
            {
                **old.model_dump(exclude={"id", "dashboard_id", "created_at", "updated_at"}),
                **changes,
            }
        )
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(e["msg"] for e in exc.errors())) from None
    await validate_tags(session, payload)
    widget.type, widget.title, widget.configuration = (
        payload.type,
        payload.title,
        payload.configuration,
    )
    await replace_children(session, widget, payload)
    touch(await require_dashboard(session, widget.dashboard_id))
    await commit(session)
    return next(w for w in await widget_reads(session, widget.dashboard_id) if w.id == identifier)


@router.delete("/dashboard-widgets/{identifier}", status_code=204)
async def remove_widget(identifier: Identifier, session: Session):
    await lock_configuration(session)
    widget = await require_widget(session, identifier)
    touch(await require_dashboard(session, widget.dashboard_id))
    await delete_widgets(session, [identifier])
    await commit(session)
    return Response(status_code=204)


@router.patch("/dashboards/{identifier}/layout", response_model=DashboardDetail)
async def save_layout(identifier: Identifier, payload: LayoutSave, session: Session):
    await lock_configuration(session)
    parent = await require_dashboard(session, identifier)
    if payload.revision != parent.revision:
        raise HTTPException(
            409, "Dashboard changed in another session; reload before saving layout"
        )
    ids = set(
        await session.scalars(
            select(DashboardWidget.id).where(DashboardWidget.dashboard_id == identifier)
        )
    )
    expected = {(i, b) for i in ids for b in ("lg", "md", "sm")}
    received = {(layout.widget_id, layout.breakpoint) for layout in payload.layouts}
    if expected != received or len(received) != len(payload.layouts):
        raise HTTPException(
            422, "Provide exactly one layout per widget and breakpoint in this dashboard"
        )
    for item in payload.layouts:
        row = await session.get(DashboardWidgetLayout, (item.widget_id, item.breakpoint))
        for key in ("x", "y", "w", "h"):
            setattr(row, key, getattr(item, key))
    touch(parent)
    await commit(session)
    return await detail(session, parent)
