"""Pure register codec used for validation and worker encoding; never opens transports."""

import struct
from decimal import Decimal, localcontext

from app.worker.decoder import FORMATS, decode_registers


def encode_registers(
    value: Decimal,
    data_type: str,
    byte_order: str,
    word_order: str,
    scale: Decimal,
    offset: Decimal,
) -> list[int]:
    if (
        data_type not in FORMATS
        or byte_order not in ("big", "little")
        or word_order not in ("big", "little")
    ):
        raise ValueError("Unsupported numeric encoding")
    if not all(x.is_finite() for x in (value, scale, offset)) or scale == 0:
        raise ValueError("Writes require finite values and nonzero scale")
    with localcontext() as context:
        context.prec = 400
        raw = (value - offset) / scale
        if not data_type.startswith("float") and raw != raw.to_integral_value():
            raise ValueError("Engineering value is not representable by the integer type and scale")
        try:
            payload = struct.pack(
                ">" + FORMATS[data_type], float(raw) if data_type.startswith("float") else int(raw)
            )
        except (OverflowError, struct.error) as exc:
            raise ValueError("Requested value exceeds the raw data type range") from exc
    words = [payload[i : i + 2] for i in range(0, len(payload), 2)]
    if word_order == "little":
        words.reverse()
    if byte_order == "little":
        words = [word[::-1] for word in words]
    registers = [int.from_bytes(word, "big") for word in words]
    decode_registers(registers, data_type, byte_order, word_order, scale, offset)
    return registers


def verification_matches(
    requested: Decimal | bool,
    actual: Decimal | bool,
    data_type: str,
    scale: Decimal = Decimal(1),
    offset: Decimal = Decimal(0),
) -> bool:
    if isinstance(requested, bool):
        return type(actual) is bool and actual == requested
    if not isinstance(actual, Decimal):
        return False
    if data_type.startswith("float"):
        # Relative to the raw value, not an arbitrary engineering unit or a large offset.
        with localcontext() as context:
            context.prec = 400
            raw = (requested - offset) / scale
            epsilon = Decimal(2) ** (-23 if data_type == "float32" else -52)
            subnormal = Decimal(2) ** (-149 if data_type == "float32" else -1074)
            tolerance = max(abs(raw) * epsilon * 2, subnormal / 2) * abs(scale)
            return abs(actual - requested) <= tolerance
    return requested == actual
