"""Application-level store-and-forward; never database replication."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SyncState(Base):
    __tablename__ = "sync_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("mode IN ('standalone','edge','cloud')", name="mode"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    mode: Mapped[str] = mapped_column(String(16))
    installation_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()))
    initialized: Mapped[bool] = mapped_column(default=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(200))
    failures: Mapped[int] = mapped_column(default=0)


class EdgeInstallation(Base):
    __tablename__ = "edge_installations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    software_version: Mapped[str | None] = mapped_column(String(50))
    runtime: Mapped[dict] = mapped_column(JSON, default=dict)


class SyncOutbox(Base):
    __tablename__ = "sync_outbox"
    __table_args__ = (Index("ix_sync_outbox_priority_id", "priority", "id"),)
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_id: Mapped[str] = mapped_column(String(36), unique=True, default=lambda: str(uuid4()))
    entity: Mapped[str] = mapped_column(String(60))
    operation: Mapped[str] = mapped_column(String(8))
    priority: Mapped[int]
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncReceipt(Base):
    __tablename__ = "sync_receipts"
    edge_id: Mapped[str] = mapped_column(
        ForeignKey("edge_installations.id", ondelete="RESTRICT"), primary_key=True
    )
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SyncMapping(Base):
    __tablename__ = "sync_mappings"
    __table_args__ = (
        UniqueConstraint("edge_id", "entity", "local_key"),
        Index("ix_sync_mappings_cloud", "entity", "cloud_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    edge_id: Mapped[str] = mapped_column(
        ForeignKey("edge_installations.id", ondelete="RESTRICT"), index=True
    )
    entity: Mapped[str] = mapped_column(String(60))
    local_key: Mapped[str] = mapped_column(String(160))
    cloud_key: Mapped[dict] = mapped_column(JSON)
    cloud_id: Mapped[int | None]
    sequence: Mapped[int] = mapped_column(BigInteger, default=0)
    deleted: Mapped[bool] = mapped_column(default=False)
    original: Mapped[dict] = mapped_column(JSON)


class RemoteRequest(Base):
    __tablename__ = "remote_requests"
    __table_args__ = (
        CheckConstraint("kind IN ('command','acknowledge')", name="kind"),
        Index("ix_remote_requests_edge_status", "edge_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    edge_id: Mapped[str] = mapped_column(ForeignKey("edge_installations.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[int]
    command_id: Mapped[int | None] = mapped_column(
        ForeignKey("commands.id", ondelete="RESTRICT"), unique=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    username: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING_EDGE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class RemoteInbox(Base):
    __tablename__ = "remote_inbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    cloud_user_id: Mapped[int]
    cloud_username: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    command_id: Mapped[int | None] = mapped_column(
        ForeignKey("commands.id", ondelete="RESTRICT"), unique=True
    )
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
