"""Application service for browsing persisted report-run history."""

from __future__ import annotations

import re
from collections.abc import Mapping
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
from retailflow.storage.mappers import JsonValue, sanitize_configuration

MISSING_REPORT_MESSAGE = (
    "Run metadata is available, but the generated file can no longer be found."
)

_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)\b(api[_ -]?token|authorization|bearer|password|secret)\b"
    r"(\s*[:=]?\s*)([^\s,;]+)"
)


@dataclass(frozen=True, slots=True)
class RunHistoryFilters:
    """Optional filters applied consistently by the run repository."""

    statuses: tuple[RunStatus, ...] = ()
    reporting_period_start: date | None = None
    reporting_period_end: date | None = None
    started_date_from: date | None = None
    started_date_to: date | None = None
    run_id_query: str = ""


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
    records = repository.list_runs(
        statuses=resolved_filters.statuses,
        reporting_period_start=resolved_filters.reporting_period_start,
        reporting_period_end=resolved_filters.reporting_period_end,
        started_from=started_from,
        started_to=started_to,
    )
    query = resolved_filters.run_id_query.strip().casefold()
    if not query:
        return records
    return tuple(record for record in records if query in record.run_id.casefold())


def run_history_dataframe(
    records: tuple[RunRecord, ...],
    report_availability: Mapping[str, bool] | None = None,
) -> pd.DataFrame:
    """Build the sortable run-history table without exposing database internals."""
    availability = report_availability or {}
    return pd.DataFrame.from_records(
        [
            {
                "Run ID": record.run_id,
                "Status": record.status.value,
                "Reporting Period": (
                    f"{record.reporting_period_start:%Y-%m-%d} to "
                    f"{record.reporting_period_end:%Y-%m-%d}"
                ),
                "Started At": record.started_at,
                "Duration": _format_duration(record.duration_seconds),
                "Source Rows": sum(record.source_row_counts.values()),
                "Excluded Rows": record.excluded_row_count,
                "Warnings": record.warning_count,
                "Errors": record.error_count,
                "Output File": _output_file_label(record, availability.get(record.run_id)),
                "Actions": (
                    "View details · Download"
                    if availability.get(record.run_id, False)
                    else "View details"
                ),
            }
            for record in records
        ]
    )


def _format_duration(duration_seconds: float | None) -> str:
    if duration_seconds is None:
        return "Not recorded"
    if duration_seconds < 60:
        return f"{duration_seconds:.2f} s"
    minutes, seconds = divmod(duration_seconds, 60)
    return f"{int(minutes)}m {seconds:.0f}s"


def _output_file_label(record: RunRecord, available: bool | None) -> str:
    if available:
        return record.report_filename or "Excel report"
    if record.report_filename or record.report_path:
        return "File unavailable"
    return "Not generated"


def report_is_available(record: RunRecord) -> bool:
    """Return whether a run still points to a readable, non-empty report file."""
    if not record.report_path:
        return False
    path = Path(record.report_path)
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def read_historical_report(
    record: RunRecord,
    *,
    known_available: bool | None = None,
) -> bytes | None:
    """Read a historical report when available, otherwise return None."""
    available = report_is_available(record) if known_available is None else known_available
    if not available or record.report_path is None:
        return None
    try:
        content = Path(record.report_path).read_bytes()
    except OSError:
        return None
    return content or None


def resolve_report_availability(records: tuple[RunRecord, ...]) -> dict[str, bool]:
    """Resolve file availability once for each currently visible history record."""
    return {record.run_id: report_is_available(record) for record in records}


def safe_source_filenames(record: RunRecord) -> dict[str, str]:
    """Return source basenames so local directory information is never displayed."""
    return {
        str(dataset): Path(str(filename)).name
        for dataset, filename in record.source_filenames.items()
    }


def safe_configuration_snapshot(record: RunRecord) -> dict[str, JsonValue]:
    """Defensively remove secret-bearing values before rendering saved settings."""
    return sanitize_configuration(record.configuration_snapshot)


def safe_failure_summary(record: RunRecord) -> str | None:
    """Redact common inline credentials from a persisted failure summary."""
    if not record.failure_summary:
        return None
    return _SENSITIVE_TEXT_PATTERN.sub(r"\1\2[redacted]", record.failure_summary)


__all__ = [
    "MISSING_REPORT_MESSAGE",
    "RunHistoryFilters",
    "get_run_repository",
    "list_run_history",
    "read_historical_report",
    "report_is_available",
    "resolve_report_availability",
    "run_history_dataframe",
    "safe_configuration_snapshot",
    "safe_failure_summary",
    "safe_source_filenames",
]
