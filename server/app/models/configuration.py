from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )


class Location(Timestamps, Base):
    __tablename__ = "locations"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"),
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Connection(Timestamps, Base):
    __tablename__ = "connections"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint("protocol IN ('modbus_rtu', 'modbus_tcp')", name="protocol"),
        CheckConstraint("timeout_ms > 0", name="timeout_positive"),
        CheckConstraint("serial_port_mode IN ('manual','auto')", name="serial_mode"),
        CheckConstraint("usb_vid IS NULL OR usb_vid BETWEEN 0 AND 65535", name="usb_vid"),
        CheckConstraint("usb_pid IS NULL OR usb_pid BETWEEN 0 AND 65535", name="usb_pid"),
        CheckConstraint(
            "serial_port_mode = 'auto' OR (usb_vid IS NULL AND usb_pid IS NULL AND usb_serial_number IS NULL AND usb_hardware_id IS NULL AND usb_manufacturer IS NULL AND usb_product IS NULL AND NOT serial_probe_enabled)",
            name="manual_identity",
        ),
        CheckConstraint("parity IS NULL OR parity IN ('N', 'E', 'O')", name="parity"),
        CheckConstraint("baud_rate IS NULL OR baud_rate > 0", name="baud_positive"),
        CheckConstraint("stop_bits IS NULL OR stop_bits IN (1, 1.5, 2)", name="stop_bits"),
        CheckConstraint("data_bits IS NULL OR data_bits IN (7, 8)", name="data_bits"),
        CheckConstraint("port IS NULL OR port BETWEEN 1 AND 65535", name="port"),
        CheckConstraint(
            "(protocol = 'modbus_rtu' AND "
            "((serial_port_mode = 'manual' AND serial_port IS NOT NULL AND length(trim(serial_port)) > 0) "
            "OR (serial_port_mode = 'auto' AND serial_port IS NULL AND usb_vid IS NOT NULL AND usb_pid IS NOT NULL)) "
            "AND baud_rate IS NOT NULL "
            "AND parity IS NOT NULL AND stop_bits IS NOT NULL AND data_bits IS NOT NULL "
            "AND host IS NULL AND port IS NULL) OR "
            "(protocol = 'modbus_tcp' AND host IS NOT NULL AND length(trim(host)) > 0 "
            "AND port IS NOT NULL AND serial_port IS NULL AND baud_rate IS NULL "
            "AND parity IS NULL AND stop_bits IS NULL AND data_bits IS NULL AND serial_port_mode = 'manual')",
            name="protocol_fields",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    protocol: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    serial_port_mode: Mapped[str] = mapped_column(
        String(6), default="manual", server_default="manual"
    )
    usb_vid: Mapped[int | None]
    usb_pid: Mapped[int | None]
    usb_serial_number: Mapped[str | None] = mapped_column(String(255))
    usb_hardware_id: Mapped[str | None] = mapped_column(String(512))
    usb_manufacturer: Mapped[str | None] = mapped_column(String(255))
    usb_product: Mapped[str | None] = mapped_column(String(255))
    serial_probe_enabled: Mapped[bool] = mapped_column(default=False, server_default=false())
    serial_port: Mapped[str | None] = mapped_column(String(255))
    baud_rate: Mapped[int | None]
    parity: Mapped[str | None] = mapped_column(String(1))
    stop_bits: Mapped[float | None]
    data_bits: Mapped[int | None]
    host: Mapped[str | None] = mapped_column(String(253))
    port: Mapped[int | None]
    timeout_ms: Mapped[int] = mapped_column(default=1000, server_default="1000")


class Device(Timestamps, Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint("slave_id BETWEEN 1 AND 247", name="slave_id"),
        UniqueConstraint("connection_id", "slave_id", name="uq_devices_connection_slave"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="RESTRICT"),
        index=True,
    )
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"),
        index=True,
    )
    slave_id: Mapped[int]
    enabled: Mapped[bool] = mapped_column(default=True, server_default=true())
    description: Mapped[str | None] = mapped_column(Text)
    connection: Mapped[Connection] = relationship(lazy="selectin")

    @property
    def connection_protocol(self) -> str:
        return self.connection.protocol


class Tag(Timestamps, Base):
    __tablename__ = "tags"
    __table_args__ = (
        CheckConstraint(
            "history_mode IN ('every_sample','fixed_interval','on_change')", name="history_mode"
        ),
        CheckConstraint(
            "history_interval_ms IS NULL OR history_interval_ms > 0", name="history_interval"
        ),
        CheckConstraint(
            "history_change_threshold IS NULL OR history_change_threshold >= 0",
            name="history_threshold",
        ),
        CheckConstraint(
            "history_retention_days IS NULL OR history_retention_days > 0", name="history_retention"
        ),
        CheckConstraint(
            "history_mode <> 'fixed_interval' OR (history_interval_ms IS NOT NULL AND history_interval_ms >= poll_interval_ms)",
            name="history_fixed",
        ),
        CheckConstraint(
            "history_mode <> 'on_change' OR data_type = 'bool' OR history_change_threshold IS NOT NULL",
            name="history_change",
        ),
        CheckConstraint(
            "history_change_threshold IS NULL OR history_change_threshold < 'Infinity'::float8",
            name="history_finite",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint("key ~ '^[a-z][a-z0-9_]{0,63}$'", name="key_format").ddl_if(
            dialect="postgresql"
        ),
        CheckConstraint(
            "register_type IN ('coil', 'discrete_input', 'input_register', 'holding_register')",
            name="register_type",
        ),
        CheckConstraint(
            "data_type IN ('bool','uint16','int16','uint32','int32','float32',"
            "'uint64','int64','float64')",
            name="data_type",
        ),
        CheckConstraint(
            "(register_type IN ('coil','discrete_input') AND data_type = 'bool') OR "
            "(register_type IN ('input_register','holding_register') AND data_type <> 'bool')",
            name="encoding",
        ),
        CheckConstraint("address BETWEEN 0 AND 65535", name="address"),
        CheckConstraint(
            "address + CASE WHEN data_type IN ('uint64','int64','float64') THEN 4 "
            "WHEN data_type IN ('uint32','int32','float32') THEN 2 ELSE 1 END <= 65536",
            name="address_span",
        ),
        CheckConstraint("byte_order IN ('big','little')", name="byte_order"),
        CheckConstraint("word_order IN ('big','little')", name="word_order"),
        CheckConstraint("poll_interval_ms > 0", name="poll_interval_positive"),
        CheckConstraint(
            "NOT writable OR register_type IN ('coil','holding_register')", name="writable_register"
        ),
        CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR min_value <= max_value", name="limits"
        ),
        CheckConstraint(
            "scale > '-Infinity'::float8 AND scale < 'Infinity'::float8 "
            "AND \"offset\" > '-Infinity'::float8 AND \"offset\" < 'Infinity'::float8 "
            "AND (min_value IS NULL OR (min_value > '-Infinity'::float8 "
            "AND min_value < 'Infinity'::float8)) "
            "AND (max_value IS NULL OR (max_value > '-Infinity'::float8 "
            "AND max_value < 'Infinity'::float8))",
            name="finite_numbers",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="RESTRICT"),
        index=True,
    )
    register_type: Mapped[str] = mapped_column(String(20), index=True)
    address: Mapped[int]
    data_type: Mapped[str] = mapped_column(String(10))
    byte_order: Mapped[str] = mapped_column(String(6), default="big", server_default="big")
    word_order: Mapped[str] = mapped_column(String(6), default="big", server_default="big")
    scale: Mapped[float] = mapped_column(Float, default=1, server_default="1")
    offset: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    unit: Mapped[str | None] = mapped_column(String(50))
    poll_interval_ms: Mapped[int] = mapped_column(default=1000, server_default="1000")
    writable: Mapped[bool] = mapped_column(default=False, server_default=false())
    history_enabled: Mapped[bool] = mapped_column(default=False, server_default=false())
    history_mode: Mapped[str] = mapped_column(
        String(20), default="every_sample", server_default="every_sample"
    )
    history_interval_ms: Mapped[int | None]
    history_change_threshold: Mapped[float | None]
    history_retention_days: Mapped[int | None]
    enabled: Mapped[bool] = mapped_column(default=True, server_default=true(), index=True)
    min_value: Mapped[float | None]
    max_value: Mapped[float | None]
    description: Mapped[str | None] = mapped_column(Text)
