from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Connection, ConnectionRuntime, Device, Tag, TagCurrentValue, WorkerRuntime
from app.schemas.runtime import (
    ConnectionStatus,
    ConnectionTest,
    DeviceStatus,
    SerialPortsRead,
    SystemRuntime,
)
from app.schemas.telemetry import utc
from app.services.configuration import get_record
from app.services.runtime import upsert_runtime, worker_alive

router = APIRouter(prefix="/api", tags=["runtime"])
Session = Annotated[AsyncSession, Depends(get_session)]
Identifier = Annotated[int, Path(ge=1, le=2147483647)]


@router.get("/system/runtime", response_model=SystemRuntime)
async def system_runtime(session: Session) -> SystemRuntime:
    worker = await session.get(WorkerRuntime, 1)
    alive = worker_alive(worker)
    return SystemRuntime(
        mode=worker.mode if alive else "unknown",
        alive=alive,
        writes_enabled=bool(alive and worker.writes_enabled),
        hostname=worker.hostname if worker else None,
        heartbeat_at=utc(worker.heartbeat_at) if worker else None,
    )


@router.get("/system/serial-ports", response_model=SerialPortsRead)
async def serial_ports(session: Session) -> SerialPortsRead:
    worker = await session.get(WorkerRuntime, 1)
    if not worker_alive(worker):
        raise HTTPException(503, "Worker unavailable; serial discovery runs on the worker host")
    return SerialPortsRead(
        worker_host=worker.hostname,
        observed_at=utc(worker.discovered_at or worker.heartbeat_at),
        ports=worker.serial_ports,
        error=worker.discovery_error,
    )


@router.get("/connections/{identifier}/status", response_model=ConnectionStatus)
async def connection_status(identifier: Identifier, session: Session) -> ConnectionStatus:
    config = await get_record(session, Connection, identifier)
    row = await session.get(ConnectionRuntime, identifier)
    worker = await session.get(WorkerRuntime, 1)
    fresh = (
        row is not None
        and row.configuration_version is not None
        and worker_alive(worker)
        and worker.mode == "modbus"
        and utc(row.configuration_version) == utc(config.updated_at)
        and row.updated_at is not None
        and (datetime.now(UTC) - utc(row.updated_at)).total_seconds() < 15
    )
    return ConnectionStatus(
        connection_id=identifier,
        detected_port=row.detected_port if fresh else None,
        detection_status=row.detection_status if fresh else None,
        detected_at=row.detected_at if row else None,
        detection_error=row.detection_error if fresh else None,
        redetect_pending=bool(
            row and row.redetect_id and row.redetect_id != row.redetect_completed_id
        ),
        state="DISABLED" if not config.enabled else row.state if fresh else "DISCONNECTED",
        last_success=row.last_success if row else None,
        last_error=row.last_error
        if fresh
        else "No active real transport; check worker mode/status",
        last_error_at=row.last_error_at if row else None,
        updated_at=row.updated_at if row else None,
    )


def test_result(row: ConnectionRuntime | None, version: datetime) -> ConnectionTest:
    if row is None or row.test_id is None:
        return ConnectionTest(test_id=None, state="NOT_REQUESTED")
    if utc(row.test_configuration_version) != utc(version):
        return ConnectionTest(
            test_id=row.test_id,
            state="EXPIRED",
            message="Configuration changed; request a new test",
        )
    if row.test_completed_id == row.test_id:
        return ConnectionTest(
            test_id=row.test_id,
            state="SUCCEEDED" if row.test_success else "FAILED",
            success=row.test_success,
            message=row.test_message,
            latency_ms=row.test_latency_ms,
        )
    if (datetime.now(UTC) - utc(row.test_requested_at)).total_seconds() >= 30:
        return ConnectionTest(
            test_id=row.test_id,
            state="EXPIRED",
            message="Worker did not complete the test within 30 seconds",
        )
    return ConnectionTest(test_id=row.test_id, state="PENDING")


@router.post("/connections/{identifier}/test", response_model=ConnectionTest, status_code=202)
async def request_test(identifier: Identifier, session: Session) -> ConnectionTest:
    config = await get_record(session, Connection, identifier, lock=True)
    worker = await session.get(WorkerRuntime, 1)
    if not worker_alive(worker):
        raise HTTPException(503, "Telemetry worker is unavailable")
    if worker.mode != "modbus":
        raise HTTPException(
            409,
            "Transport tests require TELEMETRY_SOURCE=modbus; simulator never opens device transports",
        )
    if not config.enabled:
        raise HTTPException(409, "Enable the connection before testing its transport")
    previous = await session.get(ConnectionRuntime, identifier)
    result = test_result(previous, config.updated_at)
    if result.state == "PENDING":
        return result
    token = str(uuid4())
    await upsert_runtime(
        session,
        ConnectionRuntime,
        "connection_id",
        dict(
            connection_id=identifier,
            test_id=token,
            test_requested_at=datetime.now(UTC),
            test_configuration_version=config.updated_at,
            test_success=None,
            test_message=None,
            test_latency_ms=None,
        ),
    )
    await session.commit()
    return ConnectionTest(test_id=token, state="PENDING")


@router.get("/connections/{identifier}/test", response_model=ConnectionTest)
async def read_test(identifier: Identifier, session: Session) -> ConnectionTest:
    config = await get_record(session, Connection, identifier)
    return test_result(await session.get(ConnectionRuntime, identifier), config.updated_at)


@router.get("/devices/{identifier}/status", response_model=DeviceStatus)
async def device_status(identifier: Identifier, session: Session) -> DeviceStatus:
    device = await get_record(session, Device, identifier)
    if not device.enabled or not device.connection.enabled:
        return DeviceStatus(device_id=identifier, state="DISABLED")
    rows = (
        await session.execute(
            select(
                TagCurrentValue.quality, TagCurrentValue.source_timestamp, TagCurrentValue.source
            )
            .select_from(Tag)
            .outerjoin(TagCurrentValue, Tag.id == TagCurrentValue.tag_id)
            .where(Tag.device_id == identifier, Tag.enabled)
        )
    ).all()
    worker = await session.get(WorkerRuntime, 1)
    valid_source = (
        "simulator" if worker and worker.mode == "simulator" else device.connection.protocol
    )
    qualities = [
        quality if source == valid_source or quality != "GOOD" else None
        for quality, _, source in rows
    ]
    times = [
        utc(timestamp) for _, timestamp, source in rows if timestamp and source == valid_source
    ]
    if not rows or not worker_alive(worker) or worker.mode == "disabled":
        state = "UNKNOWN"
    elif all(quality == "GOOD" for quality in qualities):
        state = "ONLINE"
    elif all(quality in ("COMM_ERROR", "STALE") for quality in qualities):
        state = "OFFLINE"
    elif any(quality in ("GOOD", "BAD", "COMM_ERROR", "STALE") for quality in qualities):
        state = "DEGRADED"
    else:
        state = "UNKNOWN"
    return DeviceStatus(device_id=identifier, state=state, last_success=max(times, default=None))


@router.post("/connections/{identifier}/redetect", status_code=202)
async def request_redetect(identifier: Identifier, session: Session) -> dict:
    config = await get_record(session, Connection, identifier, lock=True)
    worker = await session.get(WorkerRuntime, 1)
    if not worker_alive(worker):
        raise HTTPException(503, "Telemetry worker is unavailable")
    if (
        worker.mode != "modbus"
        or not config.enabled
        or config.protocol != "modbus_rtu"
        or config.serial_port_mode != "auto"
    ):
        raise HTTPException(
            409, "Re-detect requires an enabled Auto RTU connection and Modbus worker"
        )
    row = await session.get(ConnectionRuntime, identifier)
    if row and row.redetect_id and row.redetect_id != row.redetect_completed_id:
        return {"request_id": row.redetect_id, "state": "PENDING"}
    token = str(uuid4())
    await upsert_runtime(
        session,
        ConnectionRuntime,
        "connection_id",
        {"connection_id": identifier, "redetect_id": token},
    )
    await session.commit()
    return {"request_id": token, "state": "PENDING"}
