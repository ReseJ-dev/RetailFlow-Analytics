"""Tests for safe, presentation-ready run-history data."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from app.services.run_history_service import (
    RunHistoryFilters,
    list_run_history,
    read_historical_report,
    resolve_report_availability,
    run_history_dataframe,
    safe_configuration_snapshot,
    safe_failure_summary,
    safe_source_filenames,
)

from retailflow.storage import RunRecord, RunStatus


def _record(
    run_id: str = "RUN-20260131-001",
    *,
    report_path: str | None = None,
    report_filename: str | None = None,
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        started_at=datetime(2026, 1, 31, 12, tzinfo=UTC),
        completed_at=datetime(2026, 1, 31, 12, 0, 2, tzinfo=UTC),
        status=RunStatus.COMPLETED_WITH_WARNINGS,
        reporting_period_start=date(2026, 1, 1),
        reporting_period_end=date(2026, 1, 31),
        source_filenames={"orders": "/private/uploads/orders.csv"},
        source_row_counts={"orders": 12, "products": 3},
        processed_row_count=10,
        excluded_row_count=2,
        warning_count=1,
        error_count=0,
        report_path=report_path,
        report_filename=report_filename,
        report_size=8 if report_path else None,
        configuration_snapshot={
            "currency": "EUR",
            "api_token": "do-not-display",
            "nested": {"password": "hidden", "period": "2026-01"},
        },
        application_version="1.0.0",
        failure_summary="Authorization: bearer-secret failed for worksheet",
        duration_seconds=2.25,
    )


class _RepositoryStub:
    def __init__(self, records: tuple[RunRecord, ...]) -> None:
        self.records = records

    def list_runs(self, **_: object) -> tuple[RunRecord, ...]:
        return self.records


def test_run_id_search_preserves_repository_order() -> None:
    records = (_record("RUN-20260131-003"), _record("RUN-20260131-001"))

    result = list_run_history(
        _RepositoryStub(records),  # type: ignore[arg-type]
        RunHistoryFilters(run_id_query="-003"),
    )

    assert [record.run_id for record in result] == ["RUN-20260131-003"]


def test_history_table_contains_requested_columns_and_safe_file_state(tmp_path: Path) -> None:
    report = tmp_path / "report.xlsx"
    report.write_bytes(b"workbook")
    record = _record(report_path=str(report), report_filename=report.name)
    availability = resolve_report_availability((record,))

    table = run_history_dataframe((record,), availability)

    assert list(table.columns) == [
        "Run ID",
        "Status",
        "Reporting Period",
        "Started At",
        "Duration",
        "Source Rows",
        "Excluded Rows",
        "Warnings",
        "Errors",
        "Output File",
        "Actions",
    ]
    assert table.loc[0, "Source Rows"] == 15
    assert table.loc[0, "Output File"] == "report.xlsx"
    assert table.loc[0, "Actions"] == "View details · Download"
    assert read_historical_report(record, known_available=True) == b"workbook"


def test_history_details_are_sanitised_before_display() -> None:
    record = _record()

    assert safe_source_filenames(record) == {"orders": "orders.csv"}
    assert safe_configuration_snapshot(record) == {
        "currency": "EUR",
        "nested": {"period": "2026-01"},
    }
    summary = safe_failure_summary(record)
    assert summary is not None
    assert "bearer-secret" not in summary
    assert "[redacted]" in summary


def test_missing_file_is_distinct_from_preserved_metadata(tmp_path: Path) -> None:
    record = _record(
        report_path=str(tmp_path / "deleted.xlsx"),
        report_filename="deleted.xlsx",
    )
    availability = resolve_report_availability((record,))

    table = run_history_dataframe((record,), availability)

    assert availability == {record.run_id: False}
    assert table.loc[0, "Output File"] == "File unavailable"
    assert table.loc[0, "Actions"] == "View details"
    assert read_historical_report(record, known_available=False) is None
