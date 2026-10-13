"""Read-only desired-state comparisons shared by the Automation evaluator."""

from datetime import datetime
from decimal import Decimal

from app.core.config import Settings
from app.models import Connection, Device, Tag, TagCurrentValue
from app.schemas.telemetry import utc
from app.services.encoding import verification_matches

TARGET_ERROR = "Action target is disabled, stale, missing or not GOOD"


def usable_value(
    tag: Tag,
    device: Device,
    connection: Connection,
    current: TagCurrentValue | None,
    settings: Settings,
    now: datetime,
) -> Decimal | bool | None:
    if not (tag.enabled and device.enabled and connection.enabled and current):
        return None
    expected_source = "simulator" if settings.source_mode == "simulator" else connection.protocol
    if (
        current.quality != "GOOD"
        or current.error is not None
        or current.source != expected_source
        or current.source_timestamp is None
        or not 0
        <= (now - utc(current.source_timestamp)).total_seconds() * 1000
        <= tag.poll_interval_ms * settings.stale_multiplier
    ):
        return None
    value = current.value_boolean if tag.data_type == "bool" else current.value_numeric
    if value is None or (type(value) is bool) != (tag.data_type == "bool"):
        return None
    return value


def matches(tag: Tag, desired: Decimal | bool, actual: Decimal | bool) -> bool:
    return verification_matches(
        desired, actual, tag.data_type, Decimal(str(tag.scale)), Decimal(str(tag.offset))
    )
