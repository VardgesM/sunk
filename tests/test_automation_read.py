"""Incomplete mirrored metadata must not break reads or weaken mutation validation."""

import pytest
from sqlalchemy import delete, func, select
from test_automation import fixtures, rule_payload

from app.models import AutomationAction, AutomationCondition, AutomationRule, Command

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("mode", ["standalone", "cloud"])
@pytest.mark.parametrize("missing", ["conditions", "actions", "both"])
async def test_incomplete_rule_is_readable_but_cannot_be_enabled(
    api, database_sessions, mode: str, missing: str,
) -> None:
    tag, _, target = await fixtures(api, database_sessions)
    payload = rule_payload(tag, target, enabled=False)
    incomplete = (await api.post("/api/automation/rules", json=payload)).json()
    complete = (await api.post("/api/automation/rules", json={**payload, "name": "Complete"})).json()
    identifier = incomplete["id"]
    async with database_sessions() as session, session.begin():
        for name, model in (("conditions", AutomationCondition), ("actions", AutomationAction)):
            if missing in (name, "both"):
                await session.execute(delete(model).where(model.rule_id == identifier))

    api._transport.app.state.settings.application_mode = mode
    response = await api.get("/api/automation/rules")
    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()}
    assert rows[complete["id"]] == complete
    row = rows[identifier]
    for name in ("conditions", "actions"):
        assert row[name] == ([] if missing in (name, "both") else incomplete[name])
    assert row["runtime"] == incomplete["runtime"]
    assert row["updated_at"] == incomplete["updated_at"]
    detail = await api.get(f"/api/automation/rules/{identifier}")
    assert detail.status_code == 200
    assert detail.json() == row
    assert (await api.get(f"/api/automation/rules/{identifier}/executions")).json() == []

    # Reading is allowed, but neither creating nor enabling incomplete rules is.
    expected = 409 if mode == "cloud" else 422
    create_payload = {key: row[key] for key in payload}
    assert (await api.post("/api/automation/rules", json=create_payload)).status_code == expected
    assert (
        await api.patch(f"/api/automation/rules/{identifier}", json={"enabled": True})
    ).status_code == expected
    async with database_sessions() as session:
        assert not (await session.get(AutomationRule, identifier)).enabled
        assert await session.scalar(select(func.count()).select_from(AutomationRule)) == 2
        assert await session.scalar(select(func.count()).select_from(Command)) == 0
