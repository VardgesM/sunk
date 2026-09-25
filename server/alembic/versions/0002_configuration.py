"""Add relational Modbus configuration."""

import sqlalchemy as sa
from alembic import op

revision = "0002_configuration"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("protocol", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("serial_port", sa.String(length=255), nullable=True),
        sa.Column("baud_rate", sa.Integer(), nullable=True),
        sa.Column("parity", sa.String(length=1), nullable=True),
        sa.Column("stop_bits", sa.Float(), nullable=True),
        sa.Column("data_bits", sa.Integer(), nullable=True),
        sa.Column("host", sa.String(length=253), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("timeout_ms", sa.Integer(), server_default="1000", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(protocol = 'modbus_rtu' AND serial_port IS NOT NULL AND length(trim(serial_port)) > 0 AND baud_rate IS NOT NULL AND parity IS NOT NULL AND stop_bits IS NOT NULL AND data_bits IS NOT NULL AND host IS NULL AND port IS NULL) OR (protocol = 'modbus_tcp' AND host IS NOT NULL AND length(trim(host)) > 0 AND port IS NOT NULL AND serial_port IS NULL AND baud_rate IS NULL AND parity IS NULL AND stop_bits IS NULL AND data_bits IS NULL)",
            name=op.f("ck_connections_protocol_fields"),
        ),
        sa.CheckConstraint(
            "parity IS NULL OR parity IN ('N', 'E', 'O')", name=op.f("ck_connections_parity")
        ),
        sa.CheckConstraint(
            "protocol IN ('modbus_rtu', 'modbus_tcp')", name=op.f("ck_connections_protocol")
        ),
        sa.CheckConstraint(
            "baud_rate IS NULL OR baud_rate > 0", name=op.f("ck_connections_baud_positive")
        ),
        sa.CheckConstraint(
            "data_bits IS NULL OR data_bits IN (7, 8)", name=op.f("ck_connections_data_bits")
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_connections_name_not_blank")),
        sa.CheckConstraint(
            "port IS NULL OR port BETWEEN 1 AND 65535", name=op.f("ck_connections_port")
        ),
        sa.CheckConstraint(
            "stop_bits IS NULL OR stop_bits IN (1, 1.5, 2)", name=op.f("ck_connections_stop_bits")
        ),
        sa.CheckConstraint("timeout_ms > 0", name=op.f("ck_connections_timeout_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connections")),
    )
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_locations_name_not_blank")),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name=op.f("ck_locations_not_own_parent")
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["locations.id"],
            name=op.f("fk_locations_parent_id_locations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_locations")),
    )
    op.create_index(op.f("ix_locations_parent_id"), "locations", ["parent_id"], unique=False)
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column("slave_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_devices_name_not_blank")),
        sa.CheckConstraint("slave_id BETWEEN 1 AND 247", name=op.f("ck_devices_slave_id")),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connections.id"],
            name=op.f("fk_devices_connection_id_connections"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name=op.f("fk_devices_location_id_locations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devices")),
        sa.UniqueConstraint("connection_id", "slave_id", name="uq_devices_connection_slave"),
    )
    op.create_index(op.f("ix_devices_connection_id"), "devices", ["connection_id"], unique=False)
    op.create_index(op.f("ix_devices_location_id"), "devices", ["location_id"], unique=False)
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("register_type", sa.String(length=20), nullable=False),
        sa.Column("address", sa.Integer(), nullable=False),
        sa.Column("data_type", sa.String(length=10), nullable=False),
        sa.Column("byte_order", sa.String(length=6), server_default="big", nullable=False),
        sa.Column("word_order", sa.String(length=6), server_default="big", nullable=False),
        sa.Column("scale", sa.Float(), server_default="1", nullable=False),
        sa.Column("offset", sa.Float(), server_default="0", nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("poll_interval_ms", sa.Integer(), server_default="1000", nullable=False),
        sa.Column("writable", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("history_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(register_type IN ('coil','discrete_input') AND data_type = 'bool') OR (register_type IN ('input_register','holding_register') AND data_type <> 'bool')",
            name=op.f("ck_tags_encoding"),
        ),
        sa.CheckConstraint(
            "NOT writable OR register_type IN ('coil','holding_register')",
            name=op.f("ck_tags_writable_register"),
        ),
        sa.CheckConstraint(
            "address + CASE WHEN data_type IN ('uint64','int64','float64') THEN 4 WHEN data_type IN ('uint32','int32','float32') THEN 2 ELSE 1 END <= 65536",
            name=op.f("ck_tags_address_span"),
        ),
        sa.CheckConstraint("byte_order IN ('big','little')", name=op.f("ck_tags_byte_order")),
        sa.CheckConstraint(
            "data_type IN ('bool','uint16','int16','uint32','int32','float32','uint64','int64','float64')",
            name=op.f("ck_tags_data_type"),
        ),
        sa.CheckConstraint("key ~ '^[a-z][a-z0-9_]{0,63}$'", name=op.f("ck_tags_key_format")),
        sa.CheckConstraint(
            "register_type IN ('coil', 'discrete_input', 'input_register', 'holding_register')",
            name=op.f("ck_tags_register_type"),
        ),
        sa.CheckConstraint(
            "scale > '-Infinity'::float8 AND scale < 'Infinity'::float8 AND \"offset\" > '-Infinity'::float8 AND \"offset\" < 'Infinity'::float8 AND (min_value IS NULL OR (min_value > '-Infinity'::float8 AND min_value < 'Infinity'::float8)) AND (max_value IS NULL OR (max_value > '-Infinity'::float8 AND max_value < 'Infinity'::float8))",
            name=op.f("ck_tags_finite_numbers"),
        ),
        sa.CheckConstraint("word_order IN ('big','little')", name=op.f("ck_tags_word_order")),
        sa.CheckConstraint("address BETWEEN 0 AND 65535", name=op.f("ck_tags_address")),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_tags_name_not_blank")),
        sa.CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR min_value <= max_value",
            name=op.f("ck_tags_limits"),
        ),
        sa.CheckConstraint("poll_interval_ms > 0", name=op.f("ck_tags_poll_interval_positive")),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_tags_device_id_devices"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
        sa.UniqueConstraint("key", name=op.f("uq_tags_key")),
    )
    op.create_index(op.f("ix_tags_device_id"), "tags", ["device_id"], unique=False)
    op.create_index(op.f("ix_tags_enabled"), "tags", ["enabled"], unique=False)
    op.create_index(op.f("ix_tags_name"), "tags", ["name"], unique=False)
    op.create_index(op.f("ix_tags_register_type"), "tags", ["register_type"], unique=False)


def downgrade() -> None:
    op.drop_table("tags")
    op.drop_table("devices")
    op.drop_table("locations")
    op.drop_table("connections")
