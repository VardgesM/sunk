import random
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from app.services.current_values import Reading
from app.worker.sources import CommunicationError, PollTag

INTEGER_BITS = {
    "uint16": (16, False),
    "int16": (16, True),
    "uint32": (32, False),
    "int32": (32, True),
    "uint64": (64, False),
    "int64": (64, True),
}


def raw_bounds(tag: PollTag) -> tuple[Decimal, Decimal]:
    if tag.data_type in INTEGER_BITS:
        bits, signed = INTEGER_BITS[tag.data_type]
        low = Decimal(-(2 ** (bits - 1)) if signed else 0)
        high = Decimal(2 ** (bits - (1 if signed else 0)) - 1)
    else:
        high = Decimal("3.4028234e38" if tag.data_type == "float32" else "1.7976931348623157e308")
        low = -high
    if tag.scale == 0:
        if (tag.min_value is not None and tag.offset < tag.min_value) or (
            tag.max_value is not None and tag.offset > tag.max_value
        ):
            raise ValueError("Zero scale produces an offset outside the configured limits")
    else:
        for bound, minimum in ((tag.min_value, True), (tag.max_value, False)):
            if bound is None:
                continue
            raw = (bound - tag.offset) / tag.scale
            if minimum == (tag.scale > 0):
                low = max(low, raw)
            else:
                high = min(high, raw)
    if tag.data_type in INTEGER_BITS:
        low = low.to_integral_value(rounding=ROUND_CEILING)
        high = high.to_integral_value(rounding=ROUND_FLOOR)
    if low > high:
        raise ValueError("No representable raw value satisfies the configured engineering limits")
    # Development window is derived from the admissible domain, never the name/key.
    if tag.min_value is None or tag.max_value is None or tag.scale == 0:
        center = max(low, min(high, Decimal(50)))
        low, high = max(low, center - 50), min(high, center + 50)
    return low, high


class SimulatorSource:
    def __init__(self, failure_probability: float = 0, rng: random.Random | None = None) -> None:
        self.failure_probability = failure_probability
        self.rng = rng or random.Random()
        self.values: dict[int, Decimal | bool] = {}
        self.controls: dict[int, Decimal | bool] = {}
        self.control_configuration: dict[int, PollTag] = {}

    def set_control(self, tag: PollTag, value: Decimal | bool) -> None:
        self.controls[tag.id] = value
        self.control_configuration[tag.id] = tag

    def forget(self, tag_id: int, configuration: PollTag | None = None) -> None:
        # A command may arrive before the scheduler discovers a new/edited Tag.
        if configuration is None or self.control_configuration.get(tag_id) != configuration:
            self.controls.pop(tag_id, None)
            self.control_configuration.pop(tag_id, None)
        self.values.pop(tag_id, None)

    async def read(self, tag: PollTag) -> Reading:
        if self.rng.random() < self.failure_probability:
            raise CommunicationError("Simulated communication failure")
        timestamp = datetime.now(UTC)
        if self.control_configuration.get(tag.id) == tag:
            value = self.controls[tag.id]
            return Reading(value, timestamp, str(value), "simulator")
        if tag.data_type == "bool":
            allowed = [
                value
                for value in (False, True)
                if (tag.min_value is None or int(value) >= tag.min_value)
                and (tag.max_value is None or int(value) <= tag.max_value)
            ]
            if not allowed:
                raise ValueError("No boolean value satisfies the configured limits")
            value = bool(self.values.get(tag.id, False))
            if self.rng.random() < 0.5:
                value = not value
            if value not in allowed:
                value = allowed[0]
            self.values[tag.id] = value
            return Reading(value, timestamp, "true" if value else "false", "simulator")
        low, high = raw_bounds(tag)
        previous = self.values.get(tag.id)
        raw = previous if isinstance(previous, Decimal) else (low + high) / 2
        raw = max(low, min(high, raw))
        step = (high - low) / 50
        if tag.data_type in INTEGER_BITS:
            step = max(Decimal(1), step.to_integral_value(rounding=ROUND_FLOOR))
            raw += Decimal(self.rng.choice((-1, 1))) * step
            raw = raw.to_integral_value(rounding=ROUND_FLOOR)
        else:
            raw += Decimal(str(self.rng.uniform(-1, 1))) * step
        raw = max(low, min(high, raw))
        value = raw * tag.scale + tag.offset
        if not value.is_finite() or abs(value) > Decimal("1.7976931348623157e308"):
            raise ValueError("Scaled value exceeds the supported numeric range")
        self.values[tag.id] = raw
        return Reading(value, timestamp, str(raw), "simulator")
