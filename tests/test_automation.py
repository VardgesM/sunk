from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_commands import processor
from test_configuration import create, setup_tag

from app.core.config import Settings
from app.models import Command
from app.services.automation_evaluation import advance, compare
from app.services.current_values import Reading, upsert_current
from app.worker.automation import AutomationEngine

pytestmark = pytest.mark.anyio


async def fixtures(api):
    numeric = await setup_tag(api, key="input_a", poll_interval_ms=5000)
    other = await create(
        api,
        "tags",
        name="Input B",
        key="input_b",
        device_id=numeric["device_id"],
        register_type="input_register",
        address=2,
        data_type="uint16",
        poll_interval_ms=5000,
    )
    relay = await create(
        api,
        "tags",
        name="Output",
        key="output",
        device_id=numeric["device_id"],
        register_type="coil",
        address=0,
        data_type="bool",
        writable=True,
        poll_interval_ms=5000,
    )
    return numeric, other, relay


def rule_payload(tag, target, **changes):
    return {
        "name": "Test rule",
        "enabled": True,
        "conditions": [{"tag_id": tag["id"], "operator": ">", "value": "30", "hysteresis": "2"}],
        "actions": [{"target_tag_id": target["id"], "value": True}],
        **changes,
    }


async def sample(sessions, tag, value, now, quality="GOOD", source="simulator"):
    async with sessions() as session, session.begin():
        await upsert_current(
            session,
            tag["id"],
            reading=Reading(
                value if type(value) is bool else Decimal(str(value)), now, source=source
            )
            if quality == "GOOD"
            else None,
            quality=quality,
            error=None if quality == "GOOD" else "test unavailable",
        )


def engine(sessions, **settings):
    return AutomationEngine(
        SimpleNamespace(sessions=sessions),
        Settings(postgres_password="test", telemetry_source="simulator", **settings),
    )


async def commands(sessions):
    async with sessions() as session:
        return list(await session.scalars(select(Command).order_by(Command.id)))


async def test_crud_validation_and_restrictive_delete(api):
    a, _, relay = await fixtures(api)
    payload = rule_payload(a, relay)
    r = await api.post("/api/automation/rules", json=payload)
    assert r.status_code == 201, r.text
    identifier = r.json()["id"]
    assert (
        Decimal(
            (await api.get(f"/api/automation/rules/{identifier}")).json()["conditions"][0]["value"]
        )
        == 30
    )
    assert len((await api.get("/api/automation/rules")).json()) == 1
    assert (await api.delete(f"/api/tags/{a['id']}")).status_code == 409
    assert (await api.patch(f"/api/automation/rules/{identifier}", json={"enabled": False})).json()[
        "runtime"
    ]["state"] == "DISABLED"
    assert (
        await api.patch(f"/api/automation/rules/{identifier}", json={"conditions": []})
    ).status_code == 422
    assert (await api.delete(f"/api/automation/rules/{identifier}")).status_code == 204
    assert (await api.get(f"/api/automation/rules/{identifier}")).status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"conditions": []},
        {"actions": []},
        {"cooldown_ms": -1},
        {"for_duration_ms": -1},
        {"conditions": [{"tag_id": 999, "operator": ">", "value": 1}]},
        {"conditions": [{"tag_id": 1, "operator": ">", "value": True}]},
        {"conditions": [{"tag_id": 1, "operator": ">", "value": "NaN"}]},
        {"conditions": [{"tag_id": 1, "operator": ">", "value": 30, "hysteresis": -1}]},
        {"conditions": [{"tag_id": 1, "operator": "==", "value": 30, "hysteresis": 1}]},
        {"actions": [{"target_tag_id": 1, "value": 1}]},
        {"actions": [{"target_tag_id": 2, "value": 1}]},
        {"actions": [{"target_tag_id": 3, "value": 1}]},
    ],
)
async def test_invalid_rules(api, change):
    a, _, relay = await fixtures(api)
    response = await api.post("/api/automation/rules", json=rule_payload(a, relay, **change))
    assert response.status_code == 422, response.text


async def test_simulator_for_edge_hysteresis_restart_and_execution_log(api, database_sessions):
    a, _, relay = await fixtures(api)
    r = await api.post("/api/automation/rules", json=rule_payload(a, relay, for_duration_ms=2000))
    assert r.status_code == 201, r.text
    identifier = r.json()["id"]
    now = datetime.now(UTC)
    e = engine(database_sessions)
    await sample(database_sessions, a, 29, now)
    await e.tick(now)
    await sample(database_sessions, a, 31, now)
    await e.tick(now)
    assert not await commands(database_sessions)
    await e.tick(now + timedelta(seconds=1.9))
    assert not await commands(database_sessions)
    await e.tick(now + timedelta(seconds=2))
    rows = await commands(database_sessions)
    assert len(rows) == 1 and rows[0].source == "automation"
    proc = processor(database_sessions)
    assert await proc.claim() == rows[0].id
    await proc.process(rows[0].id)
    assert (await commands(database_sessions))[0].status == "SUCCESS"
    assert (await api.get(f"/api/tags/{relay['id']}/value")).json()["value_boolean"] is True
    await e.tick(now + timedelta(seconds=3))
    events = (await api.get(f"/api/automation/rules/{identifier}/executions")).json()
    assert events[0]["result"] == "SUCCESS" and events[0]["command_ids"] == [rows[0].id]
    restarted = engine(database_sessions)
    await restarted.recover()
    for index, value in enumerate([29.9, 30.1, 29.95, 30.2]):
        t = now + timedelta(seconds=4 + index)
        await sample(database_sessions, a, value, t)
        await restarted.tick(t)
    assert len(await commands(database_sessions)) == 1
    t = now + timedelta(seconds=8)
    await sample(database_sessions, a, 28, t)
    await restarted.tick(t)
    await sample(database_sessions, a, 31, t)
    await restarted.tick(t)
    await restarted.tick(t + timedelta(seconds=2))
    assert len(await commands(database_sessions)) == 2
    assert (await api.delete(f"/api/automation/rules/{identifier}")).status_code == 409


@pytest.mark.parametrize("mode,expected", [("ALL", 0), ("ANY", 1)])
async def test_multiple_conditions(api, database_sessions, mode, expected):
    a, b, relay = await fixtures(api)
    payload = rule_payload(a, relay, condition_mode=mode)
    payload["conditions"].append({"tag_id": b["id"], "operator": ">=", "value": 80})
    assert (await api.post("/api/automation/rules", json=payload)).status_code == 201
    now = datetime.now(UTC)
    await sample(database_sessions, a, 31, now)
    await sample(database_sessions, b, 79, now)
    e = engine(database_sessions)
    await e.tick(now)
    assert len(await commands(database_sessions)) == expected
    await sample(database_sessions, b, 80, now)
    await e.tick(now)
    assert len(await commands(database_sessions)) == 1


@pytest.mark.parametrize("quality", ["BAD", "STALE", "COMM_ERROR", "DISABLED"])
async def test_invalid_quality_resets_for(api, database_sessions, quality):
    a, _, relay = await fixtures(api)
    await api.post("/api/automation/rules", json=rule_payload(a, relay, for_duration_ms=2000))
    now = datetime.now(UTC)
    e = engine(database_sessions)
    await sample(database_sessions, a, 31, now)
    await e.tick(now)
    await sample(database_sessions, a, 31, now, quality)
    await e.tick(now + timedelta(seconds=1))
    await sample(database_sessions, a, 31, now + timedelta(seconds=2))
    await e.tick(now + timedelta(seconds=2))
    assert not await commands(database_sessions)
    await e.tick(now + timedelta(seconds=4))
    assert len(await commands(database_sessions)) == 1


async def test_priority_conflict_multiple_actions_and_disabled(api, database_sessions):
    a, b, relay = await fixtures(api)
    second = await create(
        api,
        "tags",
        name="Other output",
        key="other_output",
        device_id=a["device_id"],
        register_type="coil",
        address=1,
        data_type="bool",
        writable=True,
    )
    low = await api.post("/api/automation/rules", json=rule_payload(a, relay, priority=0))
    high_payload = rule_payload(a, relay, priority=50, name="Higher")
    high_payload["actions"].append({"target_tag_id": second["id"], "value": False})
    high = await api.post("/api/automation/rules", json=high_payload)
    await api.post(
        "/api/automation/rules", json=rule_payload(b, second, enabled=False, priority=100)
    )
    now = datetime.now(UTC)
    await sample(database_sessions, a, 31, now)
    await sample(database_sessions, b, 31, now)
    await engine(database_sessions).tick(now)
    assert len(await commands(database_sessions)) == 2
    assert (await api.get(f"/api/automation/rules/{low.json()['id']}/executions")).json()[0][
        "result"
    ] == "SKIPPED"
    assert (await api.get(f"/api/automation/rules/{high.json()['id']}/executions")).json()[0][
        "result"
    ] == "COMMANDS_CREATED"


async def test_physical_master_disabled_and_source_provenance(api, database_sessions):
    a, _, relay = await fixtures(api)
    r = await api.post("/api/automation/rules", json=rule_payload(a, relay))
    e = AutomationEngine(
        SimpleNamespace(sessions=database_sessions),
        Settings(postgres_password="test", telemetry_source="modbus"),
    )
    now = datetime.now(UTC)
    await sample(database_sessions, a, 31, now)
    await e.tick(now)
    assert not await commands(database_sessions)
    await sample(database_sessions, a, 31, now, source="modbus_tcp")
    await e.tick(now)
    assert not await commands(database_sessions)
    events = (await api.get(f"/api/automation/rules/{r.json()['id']}/executions")).json()
    assert events[0]["result"] == "FAILED" and "disabled" in events[0]["error"]


async def test_edit_disable_invalidates_queued_command(api, database_sessions):
    a, _, relay = await fixtures(api)
    r = await api.post("/api/automation/rules", json=rule_payload(a, relay))
    now = datetime.now(UTC)
    await sample(database_sessions, a, 31, now)
    e = engine(database_sessions)
    await e.tick(now)
    await api.patch(f"/api/automation/rules/{r.json()['id']}", json={"enabled": False})
    proc = processor(database_sessions)
    identifier = await proc.claim()
    await proc.process(identifier)
    assert (await commands(database_sessions))[0].status == "FAILED"
    await e.tick(now + timedelta(seconds=3))
    assert len(await commands(database_sessions)) == 1


async def test_cooldown_and_restart_timer_state():
    rule = SimpleNamespace(enabled=True, for_duration_ms=2000)
    r = SimpleNamespace(
        state="IDLE",
        true_since=None,
        cooldown_until=None,
        armed=True,
        condition_state=False,
        error=None,
    )
    now = datetime.now(UTC)
    assert not advance(rule, r, True, now)
    assert advance(rule, r, True, now + timedelta(seconds=2))
    r.cooldown_until = now + timedelta(seconds=10)
    assert not advance(rule, r, False, now + timedelta(seconds=3))
    assert not advance(rule, r, True, now + timedelta(seconds=4))
    assert not advance(rule, r, True, now + timedelta(seconds=9))
    assert advance(rule, r, True, now + timedelta(seconds=10))
    assert not advance(rule, r, True, now + timedelta(seconds=20))


@pytest.mark.parametrize(
    "op,value,threshold,expected",
    [
        (">", 31, 30, True),
        (">=", 30, 30, True),
        ("<", 29, 30, True),
        ("<=", 30, 30, True),
        ("==", True, True, True),
        ("!=", False, True, True),
        ("==", 30, 31, False),
    ],
)
async def test_operators(op, value, threshold, expected):
    assert compare(value, op, threshold, Decimal(0), False) is expected


async def test_boolean_condition_and_worker_restart_resets_incomplete_for(api, database_sessions):
    _, _, relay = await fixtures(api)
    r = await api.post(
        "/api/automation/rules",
        json=rule_payload(
            relay,
            relay,
            for_duration_ms=2000,
            conditions=[{"tag_id": relay["id"], "operator": "==", "value": False}],
        ),
    )
    assert r.status_code == 201
    now = datetime.now(UTC)
    await sample(database_sessions, relay, False, now)
    first = engine(database_sessions)
    await first.tick(now)
    second = engine(database_sessions)
    await second.recover()
    await second.tick(now + timedelta(seconds=1))
    await second.tick(now + timedelta(seconds=2))
    assert not await commands(database_sessions)
    await second.tick(now + timedelta(seconds=3))
    assert len(await commands(database_sessions)) == 1


async def test_stale_good_value_cannot_trigger_and_rule_reload(api, database_sessions):
    a, _, relay = await fixtures(api)
    e = engine(database_sessions)
    now = datetime.now(UTC)
    await e.tick(now)
    r = await api.post("/api/automation/rules", json=rule_payload(a, relay))
    await sample(database_sessions, a, 31, now - timedelta(seconds=60))
    await e.tick(now + timedelta(seconds=3))
    assert not await commands(database_sessions)
    runtime = (await api.get(f"/api/automation/rules/{r.json()['id']}")).json()["runtime"]
    assert runtime["state"] == "ERROR"
    await sample(database_sessions, a, 31, now + timedelta(seconds=4))
    await e.tick(now + timedelta(seconds=4))
    assert len(await commands(database_sessions)) == 1


async def test_multi_action_partial_failure_and_log(api, database_sessions):
    a, _, relay = await fixtures(api)
    target = await create(
        api,
        "tags",
        name="Other",
        key="other",
        device_id=a["device_id"],
        register_type="holding_register",
        address=4,
        data_type="uint16",
        writable=True,
    )
    payload = rule_payload(a, relay)
    payload["actions"].append({"target_tag_id": target["id"], "value": "5"})
    r = await api.post("/api/automation/rules", json=payload)
    now = datetime.now(UTC)
    await sample(database_sessions, a, 31, now)
    e = engine(database_sessions)
    await e.tick(now)
    await api.patch(f"/api/tags/{target['id']}", json={"enabled": False})
    proc = processor(database_sessions)
    for _ in range(2):
        identifier = await proc.claim()
        assert identifier is not None
        await proc.process(identifier)
    await e.tick(now + timedelta(seconds=1))
    logs = (await api.get(f"/api/automation/rules/{r.json()['id']}/executions")).json()
    assert logs[0]["result"] == "PARTIAL_FAILURE"
    assert len(logs[0]["command_ids"]) == 2
    # An invalidated target must never prevent the operator from disabling its rule.
    assert (
        await api.patch(f"/api/automation/rules/{r.json()['id']}", json={"enabled": False})
    ).status_code == 200


async def test_condition_constraints_and_foreign_keys(api, database_sessions):
    from sqlalchemy.exc import IntegrityError

    from app.models import AutomationCondition

    a, _, relay = await fixtures(api)
    r = await api.post("/api/automation/rules", json=rule_payload(a, relay))
    async with database_sessions() as session:
        session.add(
            AutomationCondition(
                rule_id=r.json()["id"],
                tag_id=a["id"],
                operator=">",
                value_boolean=True,
                hysteresis=0,
                sort_order=0,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
        session.add(
            AutomationCondition(
                rule_id=r.json()["id"],
                tag_id=999,
                operator=">",
                value_numeric=1,
                hysteresis=0,
                sort_order=0,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_unchanged_and_unrelated_inputs_do_not_re_evaluate(
    api, database_sessions, monkeypatch
):
    from unittest.mock import Mock

    import app.worker.automation as module

    a, b, relay = await fixtures(api)
    await api.post("/api/automation/rules", json=rule_payload(a, relay))
    now = datetime.now(UTC)
    await sample(database_sessions, a, 20, now)
    comparison = Mock(wraps=module.compare)
    monkeypatch.setattr(module, "compare", comparison)
    e = engine(database_sessions)
    await e.tick(now)
    assert comparison.call_count == 1
    await e.tick(now + timedelta(milliseconds=250))
    await sample(database_sessions, b, 99, now)
    await e.tick(now + timedelta(milliseconds=500))
    assert comparison.call_count == 1


async def test_quality_recovery_clears_input_error_without_replaying_edge():
    rule = SimpleNamespace(enabled=True, for_duration_ms=0)
    runtime = SimpleNamespace(state="IDLE", true_since=None, cooldown_until=None,
                              armed=True, condition_state=False, error=None)
    now = datetime.now(UTC)
    assert advance(rule, runtime, True, now)
    assert not advance(rule, runtime, None, now)
    assert runtime.state == 'ERROR'
    assert not advance(rule, runtime, True, now)
    assert runtime.state == 'ACTIVE' and runtime.error is None
