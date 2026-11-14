"""Retained configuration identity, separate from whether an active object is enabled."""

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


class Archivable:
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
