"""Local portable identity bookkeeping and recovery safety; never synchronized."""

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConfigurationIdentity(Base):
    __tablename__ = "configuration_identities"
    __table_args__ = (UniqueConstraint("entity", "local_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity: Mapped[str] = mapped_column(String(40))
    local_id: Mapped[int]


class RecoveryState(Base):
    __tablename__ = "recovery_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    restored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    backup_id: Mapped[str] = mapped_column(String(36))
    sync_review_required: Mapped[bool] = mapped_column(default=True)
