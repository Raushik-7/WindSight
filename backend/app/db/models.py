"""SQLAlchemy models for WindSight's durable storage.

Design notes
------------
* All timestamps are stored in UTC.  SQLite has no native timezone-aware type,
  so the repository layer always writes aware UTC values and re-attaches the
  UTC offset when reading back; PostgreSQL uses ``timestamptz``.
* Uniqueness follows the *verified source semantics*, not a guess:

  - ``FUELHH`` publishes one outturn value per delivery interval (with the
    possible publication of a later revision).  The natural key is therefore
    ``(dataset, start_time)`` and a revision replaces the previous row when its
    ``publishTime`` is not older - see :func:`app.db.repository.upsert_actuals`.
  - ``WINDFOR`` publishes one forecast value per delivery interval *per
    publication batch*, so ``(dataset, start_time, publish_time)`` identifies a
    record uniquely.  Distinct publication versions are never merged.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

UTC = timezone.utc


class Base(DeclarativeBase):
    """Declarative base for every WindSight table."""


def utcnow() -> datetime:
    return datetime.now(UTC)


class ActualGenerationRow(Base):
    """One half-hourly actual wind generation observation (FUELHH, WIND)."""

    __tablename__ = "actual_generation"
    __table_args__ = (
        UniqueConstraint("dataset", "start_time", name="uq_actual_dataset_interval"),
        Index("ix_actual_generation_start_time", "start_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset: Mapped[str] = mapped_column(String(32), nullable=False, default="FUELHH")
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generation_mw: Mapped[float] = mapped_column(Float, nullable=False)
    publish_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    settlement_date: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    settlement_period: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class WindForecastRow(Base):
    """One published wind generation forecast value (WINDFOR)."""

    __tablename__ = "wind_forecasts"
    __table_args__ = (
        UniqueConstraint(
            "dataset", "start_time", "publish_time", name="uq_forecast_dataset_interval_publish"
        ),
        Index("ix_wind_forecasts_start_publish", "start_time", "publish_time"),
        Index("ix_wind_forecasts_publish_time", "publish_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset: Mapped[str] = mapped_column(String(32), nullable=False, default="WINDFOR")
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    publish_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generation_mw: Mapped[float] = mapped_column(Float, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class DataImportRun(Base):
    """Audit trail for every import attempt.

    ``status`` semantics:

    * ``running``   - in progress (a crashed run stays visible and is retried).
    * ``completed`` - every requested window imported *and* coverage verified.
    * ``partial``   - some windows imported but coverage has gaps.
    * ``failed``    - nothing usable was written (or the run aborted early).
    """

    __tablename__ = "data_import_runs"
    __table_args__ = (
        Index("ix_import_runs_dataset_started", "dataset", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="elexon_live")
    range_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="delivery")
    range_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    range_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    records_retrieved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    windows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    windows_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    windows_failed_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    coverage_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    coverage_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
