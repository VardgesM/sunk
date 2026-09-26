"""USB metadata matching only. No serial I/O or brand-specific assumptions."""

import re
from dataclasses import dataclass

from app.worker.sources import Transport


@dataclass(frozen=True)
class Detection:
    status: str
    port: str | None = None
    error: str | None = None
    candidates: tuple[str, ...] = ()


def match_adapter(config: Transport, ports: list[dict]) -> Detection:
    candidates = [
        p
        for p in ports
        if p.get("vid") == config.usb_vid
        and p.get("pid") == config.usb_pid
        and p.get("vid") is not None
        and p.get("pid") is not None
    ]
    # A configured serial number is a hard identity constraint, never weakened to VID/PID.
    if config.usb_serial_number:
        candidates = [p for p in candidates if p.get("serial_number") == config.usb_serial_number]
        if len(candidates) == 1:
            return Detection("MATCHED_BY_SERIAL", candidates[0]["device"])
    hardware = config.usb_hardware_id or ""
    useful = re.sub(r"(?:USB|VID:PID=[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4})", "", hardware).strip()
    if useful and useful.lower() != "n/a":
        matches = [p for p in candidates if p.get("hwid") == config.usb_hardware_id]
        if len(matches) == 1:
            return Detection("MATCHED_BY_HARDWARE_ID", matches[0]["device"])
    if not candidates:
        return Detection("NOT_FOUND", error="Configured USB adapter not found")
    if len(candidates) == 1:
        return Detection(
            "MATCHED_BY_HARDWARE_ID", candidates[0]["device"], candidates=(candidates[0]["device"],)
        )
    return Detection(
        "AMBIGUOUS",
        error="Multiple matching USB adapters; identity is not unique",
        candidates=tuple(sorted({p["device"] for p in candidates})),
    )
