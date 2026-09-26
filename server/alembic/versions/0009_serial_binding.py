"""serial_auto_binding

Revision ID: 0009_serial_binding
Revises: 0008_alarms
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_serial_binding"
down_revision: str | Sequence[str] | None = "0008_alarms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "connection_runtime", sa.Column("detected_port", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "connection_runtime", sa.Column("detection_status", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "connection_runtime", sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("connection_runtime", sa.Column("detection_error", sa.Text(), nullable=True))
    op.add_column(
        "connection_runtime", sa.Column("redetect_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "connection_runtime",
        sa.Column("redetect_completed_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "connections",
        sa.Column("serial_port_mode", sa.String(length=6), server_default="manual", nullable=False),
    )
    op.add_column("connections", sa.Column("usb_vid", sa.Integer(), nullable=True))
    op.add_column("connections", sa.Column("usb_pid", sa.Integer(), nullable=True))
    op.add_column(
        "connections", sa.Column("usb_serial_number", sa.String(length=255), nullable=True)
    )
    op.add_column("connections", sa.Column("usb_hardware_id", sa.String(length=512), nullable=True))
    op.add_column(
        "connections", sa.Column("usb_manufacturer", sa.String(length=255), nullable=True)
    )
    op.add_column("connections", sa.Column("usb_product", sa.String(length=255), nullable=True))
    op.add_column(
        "connections",
        sa.Column(
            "serial_probe_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )

    op.drop_constraint(op.f("ck_connections_protocol_fields"), "connections", type_="check")
    op.create_check_constraint(
        op.f("ck_connections_protocol_fields"),
        "connections",
        "(protocol = 'modbus_rtu' AND ((serial_port_mode = 'manual' AND serial_port IS NOT NULL AND length(trim(serial_port)) > 0) OR (serial_port_mode = 'auto' AND serial_port IS NULL AND usb_vid IS NOT NULL AND usb_pid IS NOT NULL)) AND baud_rate IS NOT NULL AND parity IS NOT NULL AND stop_bits IS NOT NULL AND data_bits IS NOT NULL AND host IS NULL AND port IS NULL) OR (protocol = 'modbus_tcp' AND host IS NOT NULL AND length(trim(host)) > 0 AND port IS NOT NULL AND serial_port IS NULL AND baud_rate IS NULL AND parity IS NULL AND stop_bits IS NULL AND data_bits IS NULL AND serial_port_mode = 'manual')",
    )
    op.create_check_constraint(
        op.f("ck_connections_serial_mode"), "connections", "serial_port_mode IN ('manual','auto')"
    )
    op.create_check_constraint(
        op.f("ck_connections_usb_vid"),
        "connections",
        "usb_vid IS NULL OR usb_vid BETWEEN 0 AND 65535",
    )
    op.create_check_constraint(
        op.f("ck_connections_usb_pid"),
        "connections",
        "usb_pid IS NULL OR usb_pid BETWEEN 0 AND 65535",
    )
    op.create_check_constraint(
        op.f("ck_connections_manual_identity"),
        "connections",
        "serial_port_mode = 'auto' OR (usb_vid IS NULL AND usb_pid IS NULL AND usb_serial_number IS NULL AND usb_hardware_id IS NULL AND usb_manufacturer IS NULL AND usb_product IS NULL AND NOT serial_probe_enabled)",
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM connections WHERE serial_port_mode = 'auto') THEN RAISE EXCEPTION 'Convert Auto connections to Manual with explicit ports before downgrade'; END IF; END $$"
    )
    op.drop_constraint(op.f("ck_connections_protocol_fields"), "connections", type_="check")
    op.drop_constraint(op.f("ck_connections_serial_mode"), "connections", type_="check")
    op.drop_constraint(op.f("ck_connections_usb_vid"), "connections", type_="check")
    op.drop_constraint(op.f("ck_connections_usb_pid"), "connections", type_="check")
    op.drop_constraint(op.f("ck_connections_manual_identity"), "connections", type_="check")
    op.create_check_constraint(
        op.f("ck_connections_protocol_fields"),
        "connections",
        "(protocol = 'modbus_rtu' AND serial_port IS NOT NULL AND length(trim(serial_port)) > 0 AND baud_rate IS NOT NULL AND parity IS NOT NULL AND stop_bits IS NOT NULL AND data_bits IS NOT NULL AND host IS NULL AND port IS NULL) OR (protocol = 'modbus_tcp' AND host IS NOT NULL AND length(trim(host)) > 0 AND port IS NOT NULL AND serial_port IS NULL AND baud_rate IS NULL AND parity IS NULL AND stop_bits IS NULL AND data_bits IS NULL)",
    )
    op.drop_column("connections", "serial_probe_enabled")
    op.drop_column("connections", "usb_product")
    op.drop_column("connections", "usb_manufacturer")
    op.drop_column("connections", "usb_hardware_id")
    op.drop_column("connections", "usb_serial_number")
    op.drop_column("connections", "usb_pid")
    op.drop_column("connections", "usb_vid")
    op.drop_column("connections", "serial_port_mode")
    op.drop_column("connection_runtime", "redetect_completed_id")
    op.drop_column("connection_runtime", "redetect_id")
    op.drop_column("connection_runtime", "detection_error")
    op.drop_column("connection_runtime", "detected_at")
    op.drop_column("connection_runtime", "detection_status")
    op.drop_column("connection_runtime", "detected_port")
