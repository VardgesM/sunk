from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AutomationAction,
    AutomationCondition,
    AutomationRule,
    AutomationRuntime,
    Connection,
    Device,
    Tag,
)
from app.schemas.automation import ActionInput, ConditionInput, RuleInput, RuleRead, RuntimeRead
from app.services.commands import validate_write


def value_of(row: AutomationCondition | AutomationAction) -> Decimal | bool:
    return row.value_numeric if row.value_numeric is not None else row.value_boolean


async def children(
    session: AsyncSession, rule_id: int
) -> tuple[list[AutomationCondition], list[AutomationAction]]:
    conditions = list(
        await session.scalars(
            select(AutomationCondition)
            .where(AutomationCondition.rule_id == rule_id)
            .order_by(AutomationCondition.sort_order, AutomationCondition.id)
        )
    )
    actions = list(
        await session.scalars(
            select(AutomationAction)
            .where(AutomationAction.rule_id == rule_id)
            .order_by(AutomationAction.sort_order, AutomationAction.id)
        )
    )
    return conditions, actions


async def rule_read(session: AsyncSession, rule: AutomationRule) -> RuleRead:
    conditions, actions = await children(session, rule.id)
    runtime = await session.get(AutomationRuntime, rule.id)
    return RuleRead(
        **{
            key: getattr(rule, key)
            for key in (
                "id",
                "name",
                "description",
                "enabled",
                "priority",
                "condition_mode",
                "for_duration_ms",
                "cooldown_ms",
                "created_at",
                "updated_at",
            )
        },
        conditions=[
            ConditionInput(
                tag_id=c.tag_id,
                operator=c.operator,
                value=value_of(c),
                hysteresis=c.hysteresis,
                sort_order=c.sort_order,
            )
            for c in conditions
        ],
        actions=[
            ActionInput(
                target_tag_id=a.target_tag_id,
                kind=a.kind,
                value=value_of(a),
                sort_order=a.sort_order,
            )
            for a in actions
        ],
        runtime=RuntimeRead.model_validate(runtime) if runtime else None,
    )


async def validate_rule(session: AsyncSession, payload: RuleInput) -> None:
    ids = {c.tag_id for c in payload.conditions} | {a.target_tag_id for a in payload.actions}
    rows = (
        await session.execute(
            select(Tag, Device, Connection)
            .join(Device, Device.id == Tag.device_id)
            .join(Connection, Connection.id == Device.connection_id)
            .where(Tag.id.in_(ids))
            .order_by(Tag.id)
            .with_for_update(read=True, of=(Tag, Device, Connection))
        )
    ).all()
    by_id = {tag.id: (tag, device, connection) for tag, device, connection in rows}
    if set(by_id) != ids:
        raise HTTPException(422, "One or more Tags do not exist")
    for condition in payload.conditions:
        tag = by_id[condition.tag_id][0]
        if (tag.data_type == "bool") != (type(condition.value) is bool):
            raise HTTPException(422, "Condition value type does not match its Tag")
    for action in payload.actions:
        try:
            validate_write(*by_id[action.target_tag_id], action.value)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc


def add_children(session: AsyncSession, rule_id: int, payload: RuleInput) -> None:
    for cls, items in (
        (AutomationCondition, payload.conditions),
        (AutomationAction, payload.actions),
    ):
        for item in items:
            fields = item.model_dump(exclude={"value"})
            session.add(
                cls(
                    rule_id=rule_id,
                    **fields,
                    value_numeric=item.value if type(item.value) is not bool else None,
                    value_boolean=item.value if type(item.value) is bool else None,
                )
            )
