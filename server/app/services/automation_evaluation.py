"""Pure comparison and edge-state transitions; no transport or database access."""

from datetime import datetime, timedelta
from decimal import Decimal
from operator import eq, ge, gt, le, lt, ne

from app.models import AutomationRule, AutomationRuntime
from app.schemas.telemetry import utc

INPUT_ERROR = "Condition input is disabled, stale, missing or not GOOD"

OPS = {">": gt, ">=": ge, "<": lt, "<=": le, "==": eq, "!=": ne}


def compare(
    value: Decimal | bool,
    operator: str,
    threshold: Decimal | bool,
    hysteresis: Decimal,
    latched: bool,
) -> bool:
    if latched and hysteresis:
        if operator in (">", ">="):
            return value > threshold - hysteresis
        if operator in ("<", "<="):
            return value < threshold + hysteresis
    return OPS[operator](value, threshold)


def advance(
    rule: AutomationRule,
    runtime: AutomationRuntime,
    truth: bool | None,
    now: datetime,
    pending: bool = False,
) -> bool:
    """Return one trigger. Unknown quality resets FOR but never re-arms an active edge."""
    if not rule.enabled:
        runtime.state, runtime.true_since = "DISABLED", None
        return False
    if truth is None:
        runtime.state, runtime.true_since = "ERROR", None
        runtime.error = INPUT_ERROR
        return False
    if runtime.error == INPUT_ERROR:
        runtime.error = None
    runtime.condition_state = truth
    if not truth:
        runtime.error = None
        runtime.armed, runtime.true_since = True, None
        runtime.state = (
            "COOLDOWN" if runtime.cooldown_until and now < utc(runtime.cooldown_until) else "IDLE"
        )
        return False
    if runtime.true_since is None:
        runtime.true_since = now
    if pending or not runtime.armed:
        runtime.state = (
            "ERROR"
            if runtime.error
            else "COOLDOWN"
            if runtime.cooldown_until and now < utc(runtime.cooldown_until)
            else "ACTIVE"
        )
        return False
    if runtime.cooldown_until and now < utc(runtime.cooldown_until):
        runtime.state = "COOLDOWN"
        return False
    if now < utc(runtime.true_since) + timedelta(milliseconds=rule.for_duration_ms or 0):
        runtime.state = "WAITING_FOR_DURATION"
        return False
    runtime.error = None
    runtime.armed = False
    runtime.last_triggered_at = now
    runtime.state = "ACTIVE"
    return True
