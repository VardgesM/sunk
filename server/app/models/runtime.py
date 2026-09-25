from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConnectionRuntime(Base):
    __tablename__ = "connection_runtime"
    __table_args__ = (
        CheckConstraint(
            "state IN ('CONNECTED','DISCONNECTED','CONNECTING','ERROR','DISABLED')", name="state"
        ),
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="RESTRICT"), primary_key=True
    )
    state: Mapped[str] = mapped_column(
        String(16), default="DISCONNECTED", server_default="DISCONNECTED"
    )
    configuration_version: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    test_id: Mapped[str | None] = mapped_column(String(36))
    test_completed_id: Mapped[str | None] = mapped_column(String(36))
    test_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    test_configuration_version: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    test_success: Mapped[bool | None]
    test_message: Mapped[str | None] = mapped_column(Text)
    test_latency_ms: Mapped[float | None]


class WorkerRuntime(Base):
    __tablename__ = "worker_runtime"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("mode IN ('disabled','simulator','modbus')", name="mode"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(16))
    writes_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    hostname: Mapped[str] = mapped_column(String(255))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    serial_ports: Mapped[list] = mapped_column(JSON)
    discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovery_error: Mapped[str | None] = mapped_column(Text)
