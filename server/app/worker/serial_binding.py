"""Worker-only USB binding. Probe requests are read-only and configuration-derived."""

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.core.config import Settings
from app.db.session import Database
from app.models import ConnectionRuntime
from app.worker.decoder import register_count
from app.worker.modbus import (
    READ_METHODS,
    ClientState,
    ConnectionManager,
    ModbusSource,
    physical_port,
)
from app.worker.runtime import discover_ports
from app.worker.serial_identity import Detection, match_adapter

logger = logging.getLogger(__name__)


class SerialBinder:
    def __init__(self, database: Database, settings: Settings, manager: ConnectionManager):
        self.database, self.settings, self.manager = database, settings, manager
        self.next_scan = 0.0
        self.versions: dict[int, object] = {}

    def occupied(self, port: str, owner: int) -> bool:
        key = physical_port(port)
        return any(
            e.config.id != owner
            and e.config.enabled
            and e.config.protocol == "modbus_rtu"
            and e.resolved_port
            and physical_port(e.resolved_port) == key
            for e in self.manager.entries.values()
        )

    async def probe(self, entry: ClientState, candidates: tuple[str, ...]) -> Detection:
        config = entry.config
        # One deterministic readable tag for EVERY enabled configured slave with tags.
        tags = {}
        for tag in sorted(self.manager.probe_tags, key=lambda t: t.id):
            if tag.enabled and tag.transport == config and tag.register_type in READ_METHODS:
                tags.setdefault(tag.slave_id, tag)
        if not tags:
            return Detection(
                "AMBIGUOUS", error="No enabled readable Tags available for safe probing"
            )
        if len(candidates) > 8 or len(tags) > 8:
            return Detection(
                "AMBIGUOUS",
                error="Probe limit exceeded (8 candidate ports / 8 slaves); configure a unique USB identity",
            )
        matches = []
        try:
            async with asyncio.timeout(self.settings.serial_probe_budget_seconds):
                for port in candidates:
                    if self.occupied(port, config.id):
                        return Detection(
                            "AMBIGUOUS",
                            error="Candidate port belongs to another Connection; not probed",
                        )
                    async with self.manager.bus_lock(port):
                        client = self.manager.factory(replace(config, serial_port=port))
                        try:
                            async with asyncio.timeout(config.timeout_ms / 1000 + 1):
                                connected = await client.connect()
                            if not connected:
                                continue
                            for tag in tags.values():
                                count = (
                                    1 if tag.data_type == "bool" else register_count(tag.data_type)
                                )
                                async with asyncio.timeout(config.timeout_ms / 1000 + 1):
                                    response = await getattr(
                                        client, READ_METHODS[tag.register_type]
                                    )(tag.address, count=count, device_id=tag.slave_id)
                                ModbusSource.decode_response(tag, response)
                            matches.append(port)
                        except (TimeoutError, OSError, ValueError):
                            continue
                        except Exception:
                            logger.debug(
                                "Read-only serial probe failed: connection_id=%s",
                                config.id,
                                exc_info=True,
                            )
                        finally:
                            client.close()
        except TimeoutError:
            return Detection("ERROR", error="Probe time budget exhausted; no adapter selected")
        if len(matches) == 1:
            return Detection("MATCHED_BY_MODBUS_PROBE", matches[0])
        return Detection(
            "AMBIGUOUS" if matches else "NOT_FOUND",
            error="Multiple candidates answered configured reads"
            if matches
            else "No candidate answered all configured probe reads",
        )

    async def resolve(
        self, entry: ClientState, ports: list[dict], force: bool = False, error: str | None = None
    ) -> None:
        config = entry.config
        if (
            config.protocol != "modbus_rtu"
            or config.serial_port_mode != "auto"
            or not config.enabled
        ):
            return
        async with entry.lock:
            if self.manager.entries.get(config.id) is not entry:
                return
            result = Detection("ERROR", error=error) if error else match_adapter(config, ports)
            fingerprint = tuple(
                sorted(
                    (p["device"], p.get("hwid") or "", p.get("serial_number") or "")
                    for p in ports
                    if p.get("vid") == config.usb_vid and p.get("pid") == config.usb_pid
                )
            )
            fingerprint += tuple(
                (t.id, t.tag_version, t.device_version, t.slave_id, t.address)
                for t in self.manager.probe_tags
                if t.enabled and t.transport == config
            )
            if result.candidates and config.serial_probe_enabled:
                if (
                    not force
                    and entry.detection_status == "MATCHED_BY_MODBUS_PROBE"
                    and entry.detection_fingerprint == fingerprint
                    and entry.state == "CONNECTED"
                ):
                    result = Detection(entry.detection_status, entry.resolved_port)
                else:
                    self.manager.close_entry(entry)
                    entry.resolved_port = None
                    result = await self.probe(entry, result.candidates)
            if self.manager.entries.get(config.id) is not entry:
                return
            if result.port and self.occupied(result.port, config.id):
                result = Detection(
                    "ERROR", error="Detected port is already reserved by another Connection"
                )
            if force or entry.resolved_port != result.port:
                self.manager.close_entry(entry)
                entry.retry_at, entry.failures = 0, 0
                entry.device_failures.clear()
                entry.state = "DISCONNECTED"
            entry.resolved_port = result.port
            entry.detection_status, entry.detection_error = result.status, result.error
            entry.detection_fingerprint = fingerprint
            entry.detected_at = datetime.now(UTC)
            if not result.port:
                entry.state, entry.last_error, entry.last_error_at = (
                    "ERROR",
                    result.error,
                    entry.detected_at,
                )
            self.manager.check_conflicts()

    async def tick(self) -> None:
        async with self.database.sessions() as session:
            pending = list(
                await session.scalars(
                    select(ConnectionRuntime).where(
                        ConnectionRuntime.redetect_id.is_not(None),
                        (ConnectionRuntime.redetect_completed_id.is_(None))
                        | (
                            ConnectionRuntime.redetect_id != ConnectionRuntime.redetect_completed_id
                        ),
                    )
                )
            )
        requests = {r.connection_id: r.redetect_id for r in pending}
        versions = {i: e.config.version for i, e in self.manager.entries.items()}
        clock = asyncio.get_running_loop().time()
        if clock < self.next_scan and not requests and versions == self.versions:
            return
        self.next_scan = clock + self.settings.serial_scan_seconds
        self.versions = versions
        try:
            ports = await asyncio.to_thread(discover_ports)
            error = None
        except Exception:
            ports, error = [], "Worker could not enumerate USB serial adapters"
            logger.exception("USB serial enumeration failed")
        self.manager.serial_ports, self.manager.discovery_error = ports, error
        self.manager.discovered_at = datetime.now(UTC)
        # Separate connection tasks; a slow adapter never blocks polling another bus.
        entries = list(self.manager.entries.values())
        results = await asyncio.gather(
            *(self.resolve(e, ports, e.config.id in requests, error) for e in entries),
            return_exceptions=True,
        )
        for entry, result in zip(entries, results, strict=True):
            if isinstance(result, Exception):
                logger.error(
                    "USB resolution failed: connection_id=%s",
                    entry.config.id,
                    exc_info=(type(result), result, result.__traceback__),
                )
                entry.detection_status = "ERROR"
                entry.detection_error = "Adapter detection failed; check worker logs"
                self.manager.close_entry(entry)
                entry.resolved_port = None
                entry.state = "ERROR"
        async with self.database.sessions() as session, session.begin():
            for identifier, token in requests.items():
                if identifier in self.manager.entries:
                    await session.execute(
                        update(ConnectionRuntime)
                        .where(
                            ConnectionRuntime.connection_id == identifier,
                            ConnectionRuntime.redetect_id == token,
                        )
                        .values(redetect_completed_id=token)
                    )

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:
                logger.exception("USB binding failed; retrying")
            try:
                await asyncio.wait_for(stop.wait(), 1)
            except TimeoutError:
                pass
