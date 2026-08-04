"""Transactional repository for persistent report-run metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from retailflow.common.exceptions import RetailFlowError
from retailflow.storage.database import Database
from retailflow.storage.mappers import run_to_domain, sanitize_configuration
from retailflow.storage.models import RunRecord, RunRecordORM, RunStatus


class RunRepositoryError(RetailFlowError):
    """Raised when run metadata cannot be stored or retrieved."""


class RunRepository:
    """Persist run lifecycle changes while returning detached domain records."""

    def __init__(self, database: Database) -> None:
        """Bind the repository to one configured database."""
        self.database = database

    def create_run(
        self,
        *,
        reporting_period_start: date,
        reporting_period_end: date,
        source_filenames: Mapping[str, str],
        source_row_counts: Mapping[str, int],
        configuration_snapshot: Mapping[str, object],
        application_version: str,
        started_at: datetime | None = None,
    ) -> RunRecord:
        """Create a Pending run with a same-day, SQLite-safe readable ID."""
        timestamp = started_at or datetime.now(UTC)
        try:
            with self.database.session(immediate=True) as session:
                run_id = self._next_run_id(session, timestamp.date())
                record = RunRecordORM(
                    run_id=run_id,
                    started_at=timestamp,
                    status=RunStatus.PENDING.value,
                    reporting_period_start=reporting_period_start,
                    reporting_period_end=reporting_period_end,
                    source_filenames=dict(source_filenames),
                    source_row_counts={key: int(value) for key, value in source_row_counts.items()},
                    configuration_snapshot=sanitize_configuration(configuration_snapshot),
                    application_version=application_version,
                )
                session.add(record)
                session.flush()
                return run_to_domain(record)
        except IntegrityError as error:
            raise RunRepositoryError(
                "A unique run ID could not be allocated. Please try again.",
                technical_detail=str(error),
            ) from error
        except SQLAlchemyError as error:
            raise RunRepositoryError(
                "The report run could not be recorded.", technical_detail=str(error)
            ) from error

    def mark_running(self, run_id: str) -> RunRecord:
        """Move a Pending run to Running."""
        return self._update(run_id, status=RunStatus.RUNNING.value)

    def mark_completed(
        self,
        run_id: str,
        *,
        completed_at: datetime,
        processed_row_count: int,
        excluded_row_count: int,
        warning_count: int,
        error_count: int,
        report_path: str | Path,
        report_filename: str,
        report_size: int,
        duration_seconds: float,
    ) -> RunRecord:
        """Complete a run and retain aggregate report and quality metadata."""
        status = (
            RunStatus.COMPLETED_WITH_WARNINGS
            if warning_count > 0
            else RunStatus.COMPLETED
        )
        return self._update(
            run_id,
            status=status.value,
            completed_at=completed_at,
            processed_row_count=processed_row_count,
            excluded_row_count=excluded_row_count,
            warning_count=warning_count,
            error_count=error_count,
            report_path=str(report_path),
            report_filename=report_filename,
            report_size=report_size,
            duration_seconds=duration_seconds,
            failure_summary=None,
        )

    def mark_failed(
        self,
        run_id: str,
        *,
        failure_summary: str,
        completed_at: datetime,
        duration_seconds: float,
        processed_row_count: int = 0,
        excluded_row_count: int = 0,
        warning_count: int = 0,
        error_count: int = 0,
    ) -> RunRecord:
        """Mark the original run Failed without persisting exception internals."""
        return self._update(
            run_id,
            status=RunStatus.FAILED.value,
            completed_at=completed_at,
            failure_summary=failure_summary[:500],
            duration_seconds=duration_seconds,
            processed_row_count=processed_row_count,
            excluded_row_count=excluded_row_count,
            warning_count=warning_count,
            error_count=error_count,
        )

    def mark_cancelled(
        self, run_id: str, *, completed_at: datetime, duration_seconds: float
    ) -> RunRecord:
        """Mark an interrupted run Cancelled."""
        return self._update(
            run_id,
            status=RunStatus.CANCELLED.value,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
        )

    def get_run(self, run_id: str) -> RunRecord | None:
        """Return one run by ID, or None when it does not exist."""
        try:
            with self.database.session() as session:
                record = session.get(RunRecordORM, run_id)
                return run_to_domain(record) if record is not None else None
        except SQLAlchemyError as error:
            raise RunRepositoryError(
                "Run history could not be read.", technical_detail=str(error)
            ) from error

    def list_runs(
        self,
        *,
        statuses: Sequence[RunStatus] = (),
        reporting_period_start: date | None = None,
        reporting_period_end: date | None = None,
        started_from: datetime | None = None,
        started_to: datetime | None = None,
        limit: int = 500,
    ) -> tuple[RunRecord, ...]:
        """List newest runs first with optional status, period, and start-date filters."""
        query: Select[tuple[RunRecordORM]] = select(RunRecordORM)
        if statuses:
            query = query.where(RunRecordORM.status.in_([status.value for status in statuses]))
        if reporting_period_start is not None:
            query = query.where(
                RunRecordORM.reporting_period_end >= reporting_period_start
            )
        if reporting_period_end is not None:
            query = query.where(
                RunRecordORM.reporting_period_start <= reporting_period_end
            )
        if started_from is not None:
            query = query.where(RunRecordORM.started_at >= started_from)
        if started_to is not None:
            query = query.where(RunRecordORM.started_at <= started_to)
        query = query.order_by(RunRecordORM.started_at.desc(), RunRecordORM.run_id.desc()).limit(
            max(1, min(limit, 5_000))
        )
        try:
            with self.database.session() as session:
                return tuple(run_to_domain(record) for record in session.scalars(query).all())
        except SQLAlchemyError as error:
            raise RunRepositoryError(
                "Run history could not be listed.", technical_detail=str(error)
            ) from error

    def delete_run_metadata(self, run_id: str) -> bool:
        """Delete only run metadata; the generated report file is left untouched."""
        try:
            with self.database.session() as session:
                record = session.get(RunRecordORM, run_id)
                if record is None:
                    return False
                session.delete(record)
                return True
        except SQLAlchemyError as error:
            raise RunRepositoryError(
                "The run metadata could not be deleted.", technical_detail=str(error)
            ) from error

    def update_report_path(self, run_id: str, report_path: str | Path | None) -> RunRecord:
        """Update a relocated report path without changing lifecycle metadata."""
        path = Path(report_path) if report_path is not None else None
        return self._update(
            run_id,
            report_path=str(path) if path is not None else None,
            report_filename=path.name if path is not None else None,
            report_size=path.stat().st_size if path is not None and path.is_file() else None,
        )

    @staticmethod
    def _next_run_id(session: Session, run_date: date) -> str:
        prefix = f"RUN-{run_date:%Y%m%d}"
        existing = session.scalars(
            select(RunRecordORM.run_id)
            .where(RunRecordORM.run_id.like(f"{prefix}-%"))
        ).all()
        sequence = max((int(value.rsplit("-", 1)[-1]) for value in existing), default=0) + 1
        return f"{prefix}-{sequence:03d}"

    def _update(self, run_id: str, **values: object) -> RunRecord:
        try:
            with self.database.session() as session:
                record = self._required(session, run_id)
                for key, value in values.items():
                    setattr(record, key, value)
                session.flush()
                return run_to_domain(record)
        except RunRepositoryError:
            raise
        except SQLAlchemyError as error:
            raise RunRepositoryError(
                "The report run could not be updated.", technical_detail=str(error)
            ) from error

    @staticmethod
    def _required(session: Session, run_id: str) -> RunRecordORM:
        record = session.get(RunRecordORM, run_id)
        if record is None:
            raise RunRepositoryError(f"Run '{run_id}' was not found.")
        return record


def create_run_repository(
    database_url: str = "sqlite:///retailflow.sqlite3",
    *,
    create_tables: bool = True,
) -> RunRepository:
    """Create a configured repository and optionally initialize its schema."""
    database = Database(database_url)
    if create_tables:
        database.create_tables()
    return RunRepository(database)


__all__ = ["RunRepository", "RunRepositoryError", "create_run_repository"]
