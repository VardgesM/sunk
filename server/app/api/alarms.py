from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import AlarmEvent, AlarmRule, AlarmRuntime
from app.schemas.alarms import AlarmInput, AlarmRead, EventRead
from app.schemas.telemetry import utc
from app.services.alarms import (
    clear_event,
    fields,
    notify_event,
    open_event,
    rule_read,
    validate_rule,
)

router = APIRouter(prefix="/api/alarms", tags=["alarms"])
Session = Annotated[AsyncSession, Depends(get_session)]
Identifier = Annotated[int, Path(ge=1, le=2147483647)]


async def require_rule(session: AsyncSession, identifier: int) -> AlarmRule:
    rule = await session.scalar(
        select(AlarmRule).where(AlarmRule.id == identifier).with_for_update()
    )
    if rule is None:
        raise HTTPException(404, "Alarm rule not found")
    return rule


@router.get("/rules", response_model=list[AlarmRead])
async def rules(
    session: Session, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)
):
    return [
        rule_read(r)
        for r in await session.scalars(
            select(AlarmRule).order_by(AlarmRule.id).limit(limit).offset(offset)
        )
    ]


@router.post("/rules", response_model=AlarmRead, status_code=201)
async def create(payload: AlarmInput, session: Session):
    await validate_rule(session, payload)
    rule = AlarmRule(**fields(payload))
    session.add(rule)
    await session.flush()
    session.add(AlarmRuntime(rule_id=rule.id))
    await session.commit()
    return rule_read(rule)


@router.get("/rules/{identifier}", response_model=AlarmRead)
async def read(identifier: Identifier, session: Session):
    return rule_read(await require_rule(session, identifier))


@router.patch("/rules/{identifier}", response_model=AlarmRead)
async def patch(identifier: Identifier, session: Session, changes: dict = Body(...)):
    rule = await require_rule(session, identifier)
    old = rule_read(rule).model_dump(exclude={"id", "created_at", "updated_at"})
    try:
        payload = AlarmInput.model_validate({**old, **changes})
    except ValidationError as exc:
        raise HTTPException(
            422, "Invalid alarm configuration: " + "; ".join(e["msg"] for e in exc.errors())
        ) from None
    await validate_rule(session, payload)
    # Explicitly close the old configuration episode; never silently reinterpret it.
    event = await open_event(session, identifier)
    if event:
        await clear_event(session, event, datetime.now(UTC), "Rule configuration changed")
    for key, value in fields(payload).items():
        setattr(rule, key, value)
    rule.updated_at = datetime.now(UTC)
    runtime = await session.get(AlarmRuntime, identifier)
    runtime.true_since = None
    await session.commit()
    return rule_read(rule)


@router.delete("/rules/{identifier}", status_code=204)
async def remove(identifier: Identifier, session: Session):
    rule = await require_rule(session, identifier)
    if await session.scalar(select(AlarmEvent.id).where(AlarmEvent.rule_id == identifier).limit(1)):
        raise HTTPException(409, "Rule has retained alarm events; disable it instead")
    try:
        await session.execute(delete(AlarmRuntime).where(AlarmRuntime.rule_id == identifier))
        await session.delete(rule)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Rule is still referenced") from None
    return Response(status_code=204)


@router.get("/summary")
async def summary(session: Session):
    rows = (
        await session.execute(
            select(AlarmEvent.severity, func.count())
            .where(AlarmEvent.state != "CLEARED")
            .group_by(AlarmEvent.severity)
        )
    ).all()
    return {
        "active": sum(count for _, count in rows),
        "critical": sum(count for severity, count in rows if severity == "CRITICAL"),
    }


@router.get("/events", response_model=list[EventRead])
async def events(
    session: Session,
    active: bool | None = None,
    severity: Literal["INFO", "WARNING", "CRITICAL"] | None = None,
    state: Literal["ACTIVE", "ACKNOWLEDGED", "CLEARED"] | None = None,
    tag_id: int | None = Query(None, ge=1),
    rule_id: int | None = Query(None, ge=1),
    from_time: datetime | None = Query(None, alias="from"),
    to_time: datetime | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    if any(t is not None and t.tzinfo is None for t in (from_time, to_time)):
        raise HTTPException(422, "Use timestamps with a UTC offset")
    if from_time and to_time and utc(from_time) > utc(to_time):
        raise HTTPException(422, "from must not exceed to")
    query = select(AlarmEvent)
    if active is not None:
        query = query.where(
            AlarmEvent.state != "CLEARED" if active else AlarmEvent.state == "CLEARED"
        )
    for column, value in (
        (AlarmEvent.severity, severity),
        (AlarmEvent.state, state),
        (AlarmEvent.tag_id, tag_id),
        (AlarmEvent.rule_id, rule_id),
    ):
        if value is not None:
            query = query.where(column == value)
    if from_time:
        query = query.where(AlarmEvent.activated_at >= from_time)
    if to_time:
        query = query.where(AlarmEvent.activated_at <= to_time)
    return [
        EventRead.model_validate(e)
        for e in await session.scalars(
            query.order_by(AlarmEvent.activated_at.desc(), AlarmEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ]


@router.post("/events/{identifier}/acknowledge", response_model=EventRead)
async def acknowledge(identifier: Identifier, request: Request, session: Session):
    event = await session.scalar(
        select(AlarmEvent).where(AlarmEvent.id == identifier).with_for_update()
    )
    if event is None:
        raise HTTPException(404, "Alarm event not found")
    if event.state != "ACTIVE":
        raise HTTPException(409, "Only an ACTIVE alarm can be acknowledged")
    event.acknowledged_by = request.state.user.id
    event.acknowledged_by_username = request.state.user.username
    event.state, event.acknowledged_at = "ACKNOWLEDGED", datetime.now(UTC)
    event.revision += 1
    await notify_event(session, event)
    await session.commit()
    return EventRead.model_validate(event)
