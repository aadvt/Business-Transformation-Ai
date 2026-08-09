"""Declarative base + portable column mixins.

Only portable SQLAlchemy types are used anywhere in app/db/models.py so the
schema runs unchanged on Postgres (Neon) or sqlite: String for UUIDs, JSON for
structured blobs, BigInteger for paise, DateTime(timezone=True) for timestamps
(populated by Python, not server_default, so sqlite's lack of a native
timezone-aware type doesn't matter — we always hand it an aware datetime).
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.schemas.money import utc_now


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
