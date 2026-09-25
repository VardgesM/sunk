"""Decode wire words without mixing transport or scheduler concerns."""

import math
import struct
from decimal import Decimal, localcontext

from app.worker.sources import DecodeError

FORMATS = {
    "uint16": "H",
    "int16": "h",
    "uint32": "I",
    "int32": "i",
    "float32": "f",
    "uint64": "Q",
    "int64": "q",
    "float64": "d",
}


def register_count(data_type: str) -> int:
    if data_type not in FORMATS:
        raise DecodeError(f"Unsupported register data type: {data_type}")
    return struct.calcsize(">" + FORMATS[data_type]) // 2


def decode_registers(
    registers: list[int],
    data_type: str,
    byte_order: str,
    word_order: str,
    scale: Decimal,
    offset: Decimal,
) -> tuple[Decimal, str]:
    if byte_order not in ("big", "little") or word_order not in ("big", "little"):
        raise DecodeError("Invalid byte or word order")
    if len(registers) != register_count(data_type):
        raise DecodeError("Response register count does not match the configured data type")
    if any(type(word) is not int or not 0 <= word <= 65535 for word in registers):
        raise DecodeError("Response contains an invalid 16-bit register")
    words = [word.to_bytes(2, "big") for word in registers]
    if byte_order == "little":
        words = [word[::-1] for word in words]
    if word_order == "little":
        words.reverse()
    raw = struct.unpack(">" + FORMATS[data_type], b"".join(words))[0]
    if isinstance(raw, float) and not math.isfinite(raw):
        raise DecodeError("Decoded value is NaN or infinity")
    with localcontext() as context:
        context.prec = 40
        value = Decimal(str(raw)) * scale + offset
    if not value.is_finite() or abs(value) > Decimal("1.7976931348623157e308"):
        raise DecodeError("Engineering value is outside the supported finite range")
    return value, f"registers={registers}; decoded={raw}"
