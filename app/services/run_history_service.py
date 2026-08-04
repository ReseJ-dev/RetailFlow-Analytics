"""Application service for browsing persisted report-run history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from functools import lru_cache
from pathlib import Path

import pandas as pd

from retailflow.common.config import RetailFlowSettings, load_config
from retailflow.storage import (
    RunRecord,
    RunRepository,
    RunStatus,
    create_run_repository,
)

MISSING_REPORT_MESSAGE = (
    "The report file is no longer available, but the run metadata is preserved."
)


@dataclass(frozen=True, slots=True)
class RunHistoryFilters:
    """Optional filters applied consistently by the run repository."""

    statuses: tuple[RunStatus, ...] = ()
    reporting_period_start: date | None = None
    reporting_period_end: date | None = None
    started_date_from: date | None = None
    started_date_to: date | None = None


@lru_cache(maxsize=8)
def _cached_repository(database_url: str, create_tables: bool) -> RunRepository:
    return create_run_repository(database_url, create_tables=create_tables)


def get_run_repository(
    settings: RetailFlowSettings | None = None,
) -> RunRepository:
    """Return a process-cached repository configured through application settings."""
    resolved = settings or load_config()
    return _cached_repository(
        resolved.storage.database_url,
        resolved.storage.create_tables,
    )


def list_run_history(
    repository: RunRepository,
    filters: RunHistoryFilters | None = None,
) -> tuple[RunRecord, ...]:
    """List matching run records newest first."""
    resolved_filters = filters or RunHistoryFilters()
    started_from = (
        datetime.combine(resolved_filters.started_date_from, time.min, UTC)
        if resolved_filters.started_date_from is not None
        else None
    )
    started_to = (
        datetime.combine(resolved_filters.started_date_to, time.max, UTC)
        if resolved_filters.started_date_to is not None
        else None
    )
    return repository.list_runs(
        statuses=resolved_filters.statuses,
        reporting_period_start=resolved_filters.reporting_period_start,
        reporting_period_end=resolved_filters.reporting_period_end,
        started_from=started_from,
        started_to=started_to,
    )


def run_history_dataframe(records: tuple[RunRecord, ...]) -> pd.DataFrame:
    """Build the sortable run-history table without exposing database internals."""
    return pd.DataFrame.from_records(
        [
            {
                "Run ID": record.run_id,
                "Started At": record.started_at,
                "Reporting Period": (
                    f"{record.reporting_period_start:%Y-%m-%d} to "
                    f"{record.reporting_period_end:%Y-%m-%d}"
                ),
                "Files Processed": len(record.source_filenames),
                "Rows Processed": record.processed_row_count,
                "Warnings": record.warning_count,
                "Errors": record.error_count,
                "Status": record.status.value,
                "Report": record.report_filename or "Not available",
            }
            for record in records
        ]
    )


def report_is_available(record: RunRecord) -> bool:
    """Return whether a run still points to a readable, non-empty report file."""
    if not record.report_path:
        return False
    path = Path(record.report_path)
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def read_historical_report(record: RunRecord) -> bytes | None:
    """Read a historical report when available, otherwise return None."""
    if not report_is_available(record) or record.report_path is None:
        return None
    try:
        content = Path(record.report_path).read_bytes()
    except OSError:
        return None
    return content or None


__all__ = [
    "MISSING_REPORT_MESSAGE",
    "RunHistoryFilters",
    "get_run_repository",
    "list_run_history",
    "read_historical_report",
    "report_is_available",
    "run_history_dataframe",
]
