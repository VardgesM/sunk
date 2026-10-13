"""Desired-state recovery through the real queue and simulator command processor."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_automation import commands, engine, fixtures, rule_payload, sample
from test_commands import processor
from test_configuration import create

from app.core.config import Settings
from app.models import AutomationRuntime, Connection, Device, Tag
from app.schemas.telemetry import utc
from app.services.commands import enqueue_command
from app.worker.automation import AutomationEngine

pytestmark = pytest.mark.anyio


async def setup(api, sessions, **options):
    input_tag, other, target = await fixtures(api, sessions)
    response = await api.post(
        "/api/automation/rules", json=rule_payload(input_tag, target, **options)
    )
    assert response.status_code == 201, response.text
    now = datetime.now(UTC)
    await sample(sessions, input_tag, 31, now)
    await sample(sessions, target, False, now)
    return input_tag, other, target, response.json(), engine(sessions), now


async def finish(sessions):
    proc = processor(sessions)
    identifier = await proc.claim()
    assert identifier is not None
    await proc.process(identifier)
    row = (await commands(sessions))[-1]
    assert row.status == "SUCCESS"
    assert row.verified_boolean is True
    return utc(row.completed_at)


async def test_mismatch_queue_verification_and_no_repeat(api, database_sessions):
    a, _, relay, rule, e, now = await setup(api, database_sessions)
    await e.tick(now)
    for _ in range(4):
        await e.tick(now)
    rows = await commands(database_sessions)
    assert len(rows) == 1 and rows[0].source == "automation" and rows[0].requested_boolean
    done = await finish(database_sessions)
    for i in range(1, 5):
        await sample(database_sessions, a, 31, done + timedelta(seconds=i))
        await e.tick(done + timedelta(seconds=i))
    assert len(await commands(database_sessions)) == 1
    events = (await api.get(f"/api/automation/rules/{rule['id']}/executions")).json()
    assert events[0]["result"] == "SUCCESS"


async def test_initial_matched_value_needs_no_command(api, database_sessions):
    _, _, relay, _, e, now = await setup(api, database_sessions)
    await sample(database_sessions, relay, True, now)
    await e.tick(now)
    await e.tick(now + timedelta(seconds=1))
    assert not await commands(database_sessions)


async def test_power_cycle_only_target_change_drives_recovery(api, database_sessions):
    a, _, relay, rule, e, now = await setup(api, database_sessions)
    await e.tick(now)
    done = await finish(database_sessions)
    await e.tick(done)
    # Input revision does not change during recovery; target updates must wake its rule.
    lost = datetime.now(UTC)
    await sample(database_sessions, relay, True, lost, quality="COMM_ERROR")
    await e.tick(lost)
    assert len(await commands(database_sessions)) == 1
    t = datetime.now(UTC)
    await sample(database_sessions, relay, False, t)
    await e.tick(t)
    rows = await commands(database_sessions)
    assert len(rows) == 2 and rows[-1].requested_boolean and rows[-1].source == "automation"
    for _ in range(3):
        await e.tick(t)
    assert len(await commands(database_sessions)) == 2
    events = (await api.get(f"/api/automation/rules/{rule['id']}/executions")).json()
    assert events[0]["snapshot"][-1]["reason"] == "reconciliation"
    await finish(database_sessions)
    actual = (await api.get(f"/api/tags/{relay['id']}/value")).json()
    assert actual["value_boolean"] is True and actual["quality"] == "GOOD"
    await e.tick(datetime.now(UTC))
    assert len(await commands(database_sessions)) == 2


@pytest.mark.parametrize(
    "quality", ["COMM_ERROR", "STALE", "BAD", "DISABLED", "missing", "old", "source", "future"]
)
async def test_unusable_target_never_written(api, database_sessions, quality):
    _, _, relay, _, e, now = await setup(api, database_sessions)
    await sample(database_sessions, relay, True, now)
    await e.tick(now)  # First activation already satisfied, no command.
    t = now + timedelta(seconds=1)
    if quality == "missing":
        from app.models import TagCurrentValue

        async with database_sessions() as session, session.begin():
            await session.delete(await session.get(TagCurrentValue, relay["id"]))
    elif quality in ("old", "source", "future"):
        await sample(
            database_sessions,
            relay,
            False,
            t - timedelta(seconds=60)
            if quality == "old"
            else t + timedelta(seconds=60)
            if quality == "future"
            else t,
            source="modbus_tcp" if quality == "source" else "simulator",
        )
    else:
        await sample(database_sessions, relay, False, t, quality=quality)
    await e.tick(t)
    assert not await commands(database_sessions)


@pytest.mark.parametrize("status", ["QUEUED", "EXECUTING", "VERIFYING"])
@pytest.mark.parametrize("requested", [True, False])
async def test_pending_command_blocks_entire_batch(api, database_sessions, status, requested):
    _, _, relay, _, e, now = await setup(api, database_sessions)
    await sample(database_sessions, relay, True, now)
    await e.tick(now)
    async with database_sessions() as session, session.begin():
        tag = await session.get(Tag, relay["id"])
        dev = await session.get(Device, tag.device_id)
        conn = await session.get(Connection, dev.connection_id)
        command = await enqueue_command(
            session,
            tag,
            dev,
            conn,
            requested,
            mode="simulator",
            writes_enabled=False,
            physical_confirmed=False,
            max_age_seconds=30,
        )
        command.status = status
    await sample(database_sessions, relay, False, now + timedelta(seconds=1))
    await e.tick(now + timedelta(seconds=1))
    assert len(await commands(database_sessions)) == 1


@pytest.mark.parametrize(
    "change",
    ["disabled_rule", "false_condition", "bad_condition", "edited_rule", "disabled_target"],
)
async def test_inactive_or_changed_configuration_does_not_reconcile(api, database_sessions, change):
    a, _, relay, rule, e, now = await setup(api, database_sessions)
    await sample(database_sessions, relay, True, now)
    await e.tick(now)
    if change == "disabled_rule":
        await api.patch(f"/api/automation/rules/{rule['id']}", json={"enabled": False})
    if change == "edited_rule":
        await api.patch(f"/api/automation/rules/{rule['id']}", json={"name": "Edited"})
    if change == "disabled_target":
        await api.patch(f"/api/tags/{relay['id']}", json={"enabled": False})
    t = now + timedelta(seconds=5)
    await sample(
        database_sessions,
        a,
        20 if change == "false_condition" else 31,
        t,
        quality="BAD" if change == "bad_condition" else "GOOD",
    )
    await sample(database_sessions, relay, False, t)
    await e.tick(t)
    assert not await commands(database_sessions)


async def test_restart_restarts_for_and_restores_mismatch(api, database_sessions):
    a, _, relay, _, e, now = await setup(api, database_sessions, for_duration_ms=2000)
    await e.tick(now)
    await e.tick(now + timedelta(seconds=2))
    done = await finish(database_sessions)
    await e.tick(max(done, now + timedelta(seconds=3)))
    restarted = engine(database_sessions)
    await restarted.recover()
    t = now + timedelta(seconds=5)
    await sample(database_sessions, a, 31, t)
    await sample(database_sessions, relay, False, t)
    await restarted.tick(t)
    await restarted.tick(t + timedelta(seconds=1.9))
    assert len(await commands(database_sessions)) == 1
    await restarted.tick(t + timedelta(seconds=2))
    assert len(await commands(database_sessions)) == 2


async def test_cooldown_delays_but_does_not_lose_recovery(api, database_sessions):
    a, _, relay, _, e, now = await setup(api, database_sessions, cooldown_ms=5000)
    await e.tick(now)
    done = await finish(database_sessions)
    await e.tick(done)
    await sample(database_sessions, relay, False, done + timedelta(seconds=1))
    await e.tick(done + timedelta(seconds=1))
    assert len(await commands(database_sessions)) == 1
    await e.tick(done + timedelta(seconds=4.9))
    assert len(await commands(database_sessions)) == 1
    # No new input or output revision needed when cooldown expires.
    await e.tick(done + timedelta(seconds=5))
    assert len(await commands(database_sessions)) == 2


@pytest.mark.parametrize("priority", [0, 50])
async def test_higher_active_matched_rule_reserves_output(api, database_sessions, priority):
    a, b, relay, high, e, now = await setup(api, database_sessions, priority=priority)
    low = await api.post(
        "/api/automation/rules",
        json=rule_payload(
            b, relay, priority=0, actions=[{"target_tag_id": relay["id"], "value": False}]
        ),
    )
    assert low.status_code == 201
    await sample(database_sessions, b, 20, now)
    await sample(database_sessions, relay, True, now)
    await e.tick(now)  # Higher rule matches, reserves even without issuing a command.
    t = now + timedelta(seconds=1)
    await sample(database_sessions, b, 31, t)  # Only lower-priority condition changes.
    await e.tick(t)
    assert not await commands(database_sessions)
    result = (await api.get(f"/api/automation/rules/{low.json()['id']}/executions")).json()
    assert result[0]["result"] == "SKIPPED"
    await sample(database_sessions, relay, False, t + timedelta(seconds=1))
    await e.tick(t + timedelta(seconds=1))
    assert len(await commands(database_sessions)) == 1
    assert (await commands(database_sessions))[0].requested_boolean is True


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED", "EXPIRED"])
async def test_terminal_failure_never_creates_autonomous_write_retry(
    api, database_sessions, status
):
    a, _, relay, _, e, now = await setup(api, database_sessions)
    await e.tick(now)
    proc = processor(database_sessions)
    identifier = (await commands(database_sessions))[0].id
    await proc.transition(identifier, status, "Uncertain write; inspect actual state")
    await e.tick(now + timedelta(seconds=1))
    restarted = engine(database_sessions)
    await restarted.recover()
    for i in range(2, 6):
        t = now + timedelta(seconds=i)
        await sample(database_sessions, a, 31, t)
        await sample(database_sessions, relay, False, t)
        await restarted.tick(t)
    assert len(await commands(database_sessions)) == 1


async def test_modbus_disabled_reconciliation_cannot_bypass_queue(api, database_sessions):
    a, _, relay, _, _, now = await setup(api, database_sessions)
    settings = Settings(
        postgres_password="test", telemetry_source="modbus", modbus_writes_enabled=False
    )
    e = AutomationEngine(SimpleNamespace(sessions=database_sessions), settings)
    await sample(database_sessions, a, 31, now, source="modbus_tcp")
    await sample(database_sessions, relay, True, now, source="modbus_tcp")
    await e.tick(now)
    t = now + timedelta(seconds=1)
    await sample(database_sessions, relay, False, t, source="modbus_tcp")
    await e.tick(t)
    assert not await commands(database_sessions)
    async with database_sessions() as session:
        runtime = await session.scalar(select(AutomationRuntime))
        assert runtime.last_result == "FAILED" and "disabled" in runtime.error


async def test_numeric_tolerance_and_only_mismatched_targets(api, database_sessions):
    a, _, relay = await fixtures(api, database_sessions)
    numeric = await create(
        api,
        "tags",
        name="Setpoint",
        key="setpoint",
        device_id=a["device_id"],
        register_type="holding_register",
        address=10,
        data_type="float32",
        writable=True,
        scale=0.1,
        offset=2,
        poll_interval_ms=5000,
    )
    payload = rule_payload(
        a,
        relay,
        actions=[
            {"target_tag_id": relay["id"], "value": True},
            {"target_tag_id": numeric["id"], "value": "2.1"},
        ],
    )
    assert (await api.post("/api/automation/rules", json=payload)).status_code == 201
    now = datetime.now(UTC)
    await sample(database_sessions, a, 31, now)
    await sample(database_sessions, relay, True, now)
    await sample(database_sessions, numeric, Decimal("2.100000001"), now)
    e = engine(database_sessions)
    await e.tick(now)
    assert not await commands(database_sessions)
    t = now + timedelta(seconds=1)
    await sample(database_sessions, numeric, 2, t)
    await e.tick(t)
    rows = await commands(database_sessions)
    assert (
        len(rows) == 1
        and rows[0].tag_id == numeric["id"]
        and rows[0].requested_numeric == Decimal("2.1")
    )


async def test_restart_requires_post_restart_target_read(api, database_sessions):
    a, _, relay, _, e, now = await setup(api, database_sessions)
    await e.tick(now)
    done = await finish(database_sessions)
    await e.tick(done)
    t = datetime.now(UTC)
    await sample(database_sessions, relay, False, t)
    restarted = engine(database_sessions)
    await restarted.recover()
    await restarted.tick(datetime.now(UTC))
    assert len(await commands(database_sessions)) == 1
    t = datetime.now(UTC)
    await sample(database_sessions, relay, False, t)
    await restarted.tick(t)
    assert len(await commands(database_sessions)) == 2


async def test_failed_correction_is_not_retried_after_more_samples_or_restart(
    api, database_sessions
):
    a, _, relay, _, e, now = await setup(api, database_sessions)
    await e.tick(now)
    done = await finish(database_sessions)
    await e.tick(done)
    t = done + timedelta(seconds=1)
    await sample(database_sessions, relay, False, t)
    await e.tick(t)
    correction = (await commands(database_sessions))[-1]
    assert correction.id != (await commands(database_sessions))[0].id
    proc = processor(database_sessions)
    await proc.transition(correction.id, "FAILED", "Read-back mismatch; not retried")
    await e.tick(t + timedelta(seconds=1))
    restarted = engine(database_sessions)
    await restarted.recover()
    for i in range(2, 5):
        await sample(database_sessions, a, 31, t + timedelta(seconds=i))
        await sample(database_sessions, relay, False, t + timedelta(seconds=i))
        await restarted.tick(t + timedelta(seconds=i))
    assert len(await commands(database_sessions)) == 2


async def test_initial_unreadable_target_waits_without_consuming_edge(api, database_sessions):
    _, _, relay, rule, e, now = await setup(api, database_sessions)
    await sample(database_sessions, relay, False, now, quality="COMM_ERROR")
    await e.tick(now)
    assert not await commands(database_sessions)
    assert not (await api.get(f"/api/automation/rules/{rule['id']}/executions")).json()
    t = now + timedelta(seconds=1)
    await sample(database_sessions, relay, False, t)
    await e.tick(t)
    assert len(await commands(database_sessions)) == 1


async def test_lower_successful_rule_cannot_fight_higher_active_rule(api, database_sessions):
    a, b, relay, low, e, now = await setup(api, database_sessions, priority=0)
    high_payload = rule_payload(
        b, relay, priority=50, actions=[{"target_tag_id": relay["id"], "value": False}]
    )
    assert (await api.post("/api/automation/rules", json=high_payload)).status_code == 201
    await sample(database_sessions, b, 20, now)
    await e.tick(now)
    done = await finish(database_sessions)
    await e.tick(done)
    t = done + timedelta(seconds=1)
    await sample(database_sessions, b, 31, t)
    await e.tick(t)
    proc = processor(database_sessions)
    identifier = await proc.claim()
    assert identifier is not None
    await proc.process(identifier)
    assert (await commands(database_sessions))[-1].verified_boolean is False
    for i in range(2, 5):
        await sample(database_sessions, a, 31, t + timedelta(seconds=i))
        await sample(database_sessions, relay, False, t + timedelta(seconds=i))
        await e.tick(t + timedelta(seconds=i))
    assert len(await commands(database_sessions)) == 2
    # Higher condition clears: lower successful, still-active rule can own the output again.
    await sample(database_sessions, b, 20, t + timedelta(seconds=5))
    await e.tick(t + timedelta(seconds=5))
    assert len(await commands(database_sessions)) == 3
    assert (await commands(database_sessions))[-1].requested_boolean is True


async def test_skipped_multitarget_rule_does_not_reserve_unclaimed_output(api, database_sessions):
    a, _, relay, _, e, now = await setup(api, database_sessions, priority=100)
    other = await create(
        api,
        "tags",
        name="Independent",
        key="independent",
        device_id=a["device_id"],
        register_type="coil",
        address=4,
        data_type="bool",
        writable=True,
        poll_interval_ms=5000,
    )
    middle = rule_payload(
        a,
        relay,
        priority=50,
        actions=[
            {"target_tag_id": relay["id"], "value": False},
            {"target_tag_id": other["id"], "value": False},
        ],
    )
    assert (await api.post("/api/automation/rules", json=middle)).status_code == 201
    assert (await api.post("/api/automation/rules", json=rule_payload(a, other))).status_code == 201
    now = datetime.now(UTC)
    await sample(database_sessions, a, 31, now)
    await sample(database_sessions, relay, True, now)
    await sample(database_sessions, other, False, now)
    await e.tick(now)
    rows = await commands(database_sessions)
    assert len(rows) == 1 and rows[0].tag_id == other["id"] and rows[0].requested_boolean
