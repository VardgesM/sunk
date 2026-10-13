"""Fresh, stateful edit/restart activation; real queue and simulator only."""

from datetime import UTC, datetime, timedelta

import pytest
from test_automation import commands, engine, rule_payload, sample
from test_automation_reconciliation import finish, setup

from app.schemas.telemetry import utc

pytestmark = pytest.mark.anyio


async def edit(api, rule, **changes):
    response = await api.patch(
        f"/api/automation/rules/{rule['id']}", json={"description": "Edited", **changes}
    )
    assert response.status_code == 200, response.text
    return utc(datetime.fromisoformat(response.json()["updated_at"]))


@pytest.mark.parametrize("previous", ["unexecuted", "matched", "successful", "disabled"])
async def test_edit_true_state_queues_once_without_false_edge(api, database_sessions, previous):
    a, _, target, rule, e, now = await setup(api, database_sessions, enabled=previous != "disabled")
    count = 0
    if previous == "matched":
        await sample(database_sessions, target, True, now)
        await e.tick(now)
    elif previous == "successful":
        await e.tick(now)
        done = await finish(database_sessions)
        await e.tick(done)
        count = 1
    else:
        await sample(database_sessions, a, 31, now, quality="COMM_ERROR")
        await e.tick(now)
    modified = await edit(api, rule, enabled=True)
    t = max(now, modified) + timedelta(seconds=4)
    await sample(database_sessions, a, 31, t)
    await sample(database_sessions, target, False, t)
    await e.tick(t)
    for _ in range(3):
        await e.tick(t)
    rows = await commands(database_sessions)
    assert len(rows) == count + 1
    assert rows[-1].source == "automation" and rows[-1].requested_boolean is True


@pytest.mark.parametrize("state", ["false", "matched", "disabled", "COMM_ERROR", "STALE", "BAD"])
async def test_edit_does_not_bypass_conditions_quality_or_enablement(api, database_sessions, state):
    a, _, target, rule, e, now = await setup(api, database_sessions)
    modified = await edit(api, rule, enabled=state != "disabled")
    t = modified + timedelta(seconds=4)
    await sample(database_sessions, a, 20 if state == "false" else 31, t)
    await sample(
        database_sessions,
        target,
        state == "matched",
        t,
        quality=state if state in ("COMM_ERROR", "STALE", "BAD") else "GOOD",
    )
    await e.tick(t)
    assert not await commands(database_sessions)


@pytest.mark.parametrize("first_fresh", ["condition", "target"])
@pytest.mark.parametrize("boundary", ["edit", "restart"])
async def test_both_sides_must_have_post_boundary_readings(
    api, database_sessions, first_fresh, boundary
):
    a, _, target, rule, e, now = await setup(api, database_sessions)
    await sample(database_sessions, target, True, now)
    await e.tick(now)
    # Wrong but recent cached output must not authorize actuation after either boundary.
    await sample(database_sessions, target, False, datetime.now(UTC))
    if boundary == "edit":
        boundary_time = await edit(api, rule)
    else:
        e = engine(database_sessions)
        await e.recover()
        boundary_time = e.recovered_at
    t = boundary_time + timedelta(seconds=4)
    await e.tick(t)
    assert not await commands(database_sessions)
    await sample(
        database_sessions,
        a if first_fresh == "condition" else target,
        31 if first_fresh == "condition" else False,
        t,
    )
    await e.tick(t)
    assert not await commands(database_sessions)
    await sample(
        database_sessions,
        target if first_fresh == "condition" else a,
        False if first_fresh == "condition" else 31,
        t,
    )
    await e.tick(t)
    assert len(await commands(database_sessions)) == 1


async def test_edit_for_timer_starts_with_fresh_inputs_and_resets_on_invalid_quality(
    api, database_sessions
):
    a, _, target, rule, e, now = await setup(api, database_sessions)
    modified = await edit(api, rule, for_duration_ms=2000)
    t = modified + timedelta(seconds=4)
    await sample(database_sessions, a, 31, t)
    await sample(database_sessions, target, False, t)
    await e.tick(t)
    await e.tick(t + timedelta(seconds=1.9))
    assert not await commands(database_sessions)
    await sample(database_sessions, a, 31, t + timedelta(seconds=2), quality="BAD")
    await e.tick(t + timedelta(seconds=2))
    await sample(database_sessions, a, 31, t + timedelta(seconds=3))
    await e.tick(t + timedelta(seconds=3))
    await e.tick(t + timedelta(seconds=4.9))
    assert not await commands(database_sessions)
    await e.tick(t + timedelta(seconds=5))
    assert len(await commands(database_sessions)) == 1


async def test_edit_preserves_existing_success_cooldown(api, database_sessions):
    a, _, target, rule, e, now = await setup(api, database_sessions, cooldown_ms=10000)
    await e.tick(now)
    done = await finish(database_sessions)
    await e.tick(done)
    await edit(api, rule)
    t = done + timedelta(seconds=4)
    await sample(database_sessions, a, 31, t)
    await sample(database_sessions, target, False, t)
    await e.tick(t)
    await e.tick(done + timedelta(seconds=9.9))
    assert len(await commands(database_sessions)) == 1
    await e.tick(done + timedelta(seconds=10))
    assert len(await commands(database_sessions)) == 2


async def test_edit_while_previous_equivalent_command_pending_never_duplicates(
    api, database_sessions
):
    a, _, target, rule, e, now = await setup(api, database_sessions)
    await e.tick(now)
    modified = await edit(api, rule)
    t = modified + timedelta(seconds=4)
    await sample(database_sessions, a, 31, t)
    await sample(database_sessions, target, False, t)
    await e.tick(t)
    assert len(await commands(database_sessions)) == 1
    # The processor rejects the queued old configuration without touching a transport.
    from test_commands import processor

    proc = processor(database_sessions)
    identifier = await proc.claim()
    await proc.process(identifier)
    assert (await commands(database_sessions))[0].status == "FAILED"
    await e.tick(t + timedelta(seconds=1))
    rows = await commands(database_sessions)
    assert len(rows) == 2 and rows[-1].status == "QUEUED"
    await e.tick(t + timedelta(seconds=2))
    assert len(await commands(database_sessions)) == 2


async def test_edited_lower_priority_cannot_override_active_higher_rule(api, database_sessions):
    a, b, target, _, e, now = await setup(api, database_sessions, priority=100)
    response = await api.post(
        "/api/automation/rules",
        json=rule_payload(
            b, target, priority=0, actions=[{"target_tag_id": target["id"], "value": False}]
        ),
    )
    assert response.status_code == 201
    now = datetime.now(UTC)
    await sample(database_sessions, a, 31, now)
    await sample(database_sessions, b, 20, now)
    await sample(database_sessions, target, True, now)
    await e.tick(now)
    modified = await edit(api, response.json())
    t = modified + timedelta(seconds=4)
    await sample(database_sessions, a, 31, t)
    await sample(database_sessions, b, 31, t)
    await sample(database_sessions, target, True, t)
    await e.tick(t)
    assert not await commands(database_sessions)
    events = (await api.get(f"/api/automation/rules/{response.json()['id']}/executions")).json()
    assert events[0]["result"] == "SKIPPED"


@pytest.mark.parametrize("mode,expected", [("ALL", 0), ("ANY", 1)])
async def test_edited_rule_preserves_all_any(api, database_sessions, mode, expected):
    a, b, target, rule, e, now = await setup(api, database_sessions)
    modified = await edit(
        api,
        rule,
        condition_mode=mode,
        conditions=[
            {"tag_id": a["id"], "operator": ">", "value": 30},
            {"tag_id": b["id"], "operator": ">", "value": 80},
        ],
    )
    t = modified + timedelta(seconds=4)
    await sample(database_sessions, a, 31, t)
    await sample(database_sessions, b, 79, t)
    await sample(database_sessions, target, False, t)
    await e.tick(t)
    assert len(await commands(database_sessions)) == expected


@pytest.mark.parametrize("kind", ["PULSE", "TOGGLE", "ONE_SHOT"])
async def test_non_stateful_kinds_remain_unsupported(api, database_sessions, kind):
    _, _, target, rule, _, _ = await setup(api, database_sessions)
    response = await api.patch(
        f"/api/automation/rules/{rule['id']}",
        json={
            "actions": [{"target_tag_id": target["id"], "kind": kind, "value": True}],
        },
    )
    assert response.status_code == 422
    assert not await commands(database_sessions)
