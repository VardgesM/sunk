from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Response
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import (
    AutomationAction,
    AutomationCondition,
    AutomationExecution,
    AutomationExecutionCommand,
    AutomationRule,
    AutomationRuntime,
)
from app.schemas.automation import ExecutionRead, RuleInput, RuleRead
from app.services.automation import add_children, rule_read, validate_rule

router = APIRouter(prefix="/api/automation/rules", tags=["automation"])
Session = Annotated[AsyncSession, Depends(get_session)]
Identifier = Annotated[int, Path(ge=1, le=2147483647)]


async def require_rule(session: AsyncSession, identifier: int) -> AutomationRule:
    rule = await session.scalar(
        select(AutomationRule).where(AutomationRule.id == identifier).with_for_update()
    )
    if rule is None:
        raise HTTPException(404, "Automation rule not found")
    return rule


@router.get("", response_model=list[RuleRead])
async def list_rules(
    session: Session, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)
):
    rows = await session.scalars(
        select(AutomationRule)
        .order_by(AutomationRule.priority.desc(), AutomationRule.id)
        .limit(limit)
        .offset(offset)
    )
    return [await rule_read(session, rule) for rule in rows]


@router.post("", response_model=RuleRead, status_code=201)
async def create_rule(payload: RuleInput, session: Session):
    await validate_rule(session, payload)
    rule = AutomationRule(**payload.model_dump(exclude={"conditions", "actions"}))
    session.add(rule)
    await session.flush()
    add_children(session, rule.id, payload)
    session.add(AutomationRuntime(rule_id=rule.id, state="IDLE" if rule.enabled else "DISABLED"))
    await session.commit()
    return await rule_read(session, rule)


@router.get("/{identifier}", response_model=RuleRead)
async def read_rule(identifier: Identifier, session: Session):
    return await rule_read(session, await require_rule(session, identifier))


@router.patch("/{identifier}", response_model=RuleRead)
async def patch_rule(identifier: Identifier, session: Session, changes: dict = Body(...)):
    rule = await require_rule(session, identifier)
    old = (await rule_read(session, rule)).model_dump(
        exclude={"id", "created_at", "updated_at", "runtime"}
    )
    try:
        payload = RuleInput.model_validate({**old, **changes})
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    if changes != {"enabled": False}:
        await validate_rule(session, payload)
    for key, value in payload.model_dump(exclude={"conditions", "actions"}).items():
        setattr(rule, key, value)
    rule.updated_at = datetime.now(UTC)
    for cls in (AutomationCondition, AutomationAction):
        await session.execute(delete(cls).where(cls.rule_id == identifier))
    add_children(session, identifier, payload)
    runtime = await session.get(AutomationRuntime, identifier)
    runtime.state = "IDLE" if rule.enabled else "DISABLED"
    runtime.true_since = None
    runtime.condition_state = False
    runtime.armed = False  # Edited/enabled rules must observe a valid false state before firing.
    runtime.latches = {}
    runtime.error = None
    await session.commit()
    return await rule_read(session, rule)


@router.delete("/{identifier}", status_code=204)
async def delete_rule(identifier: Identifier, session: Session):
    rule = await require_rule(session, identifier)
    if await session.scalar(
        select(AutomationExecution.id).where(AutomationExecution.rule_id == identifier).limit(1)
    ):
        raise HTTPException(409, "Rule has retained execution history; disable it instead")
    try:
        for cls in (AutomationCondition, AutomationAction, AutomationRuntime):
            await session.execute(delete(cls).where(cls.rule_id == identifier))
        await session.delete(rule)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Rule is referenced") from exc
    return Response(status_code=204)


@router.get("/{identifier}/executions", response_model=list[ExecutionRead])
async def executions(
    identifier: Identifier, session: Session, limit: int = Query(50, ge=1, le=200)
):
    await require_rule(session, identifier)
    rows = list(
        await session.scalars(
            select(AutomationExecution)
            .where(AutomationExecution.rule_id == identifier)
            .order_by(AutomationExecution.id.desc())
            .limit(limit)
        )
    )
    result = []
    for row in rows:
        ids = list(
            await session.scalars(
                select(AutomationExecutionCommand.command_id)
                .where(AutomationExecutionCommand.execution_id == row.id)
                .order_by(AutomationExecutionCommand.command_id)
            )
        )
        result.append(
            ExecutionRead(
                **{
                    k: getattr(row, k)
                    for k in (
                        "id",
                        "rule_id",
                        "triggered_at",
                        "completed_at",
                        "snapshot",
                        "result",
                        "error",
                    )
                },
                command_ids=ids,
            )
        )
    return result
