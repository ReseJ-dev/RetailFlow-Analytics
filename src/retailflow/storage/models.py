"""ORM and domain models for persistent report-run history."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import JSON, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class RunStatus(StrEnum):
    """Supported lifecycle states for one report-generation attempt."""

    PENDING = "Pending"
    RUNNING = "Running"
    COMPLETED = "Completed"
    COMPLETED_WITH_WARNINGS = "Completed with Warnings"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class Base(DeclarativeBase):
    """Declarative base for RetailFlow-owned database tables."""


class RunRecordORM(Base):
    """SQLAlchemy persistence model; never returned directly to the UI."""

    __tablename__ = "report_runs"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reporting_period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    reporting_period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source_filenames: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    source_row_counts: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    processed_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    excluded_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_path: Mapped[str | None] = mapped_column(Text)
    report_filename: Mapped[str | None] = mapped_column(String(255))
    report_size: Mapped[int | None] = mapped_column(Integer)
    configuration_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    application_version: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_summary: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float | None] = mapped_column(Float)


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Immutable run-history model safe to expose through application services."""

    run_id: str
    started_at: datetime
    completed_at: datetime | None
    status: RunStatus
    reporting_period_start: date
    reporting_period_end: date
    source_filenames: Mapping[str, str]
    source_row_counts: Mapping[str, int]
    processed_row_count: int
    excluded_row_count: int
    warning_count: int
    error_count: int
    report_path: str | None
    report_filename: str | None
    report_size: int | None
    configuration_snapshot: Mapping[str, object]
    application_version: str
    failure_summary: str | None
    duration_seconds: float | None


__all__ = ["Base", "RunRecord", "RunRecordORM", "RunStatus"]
