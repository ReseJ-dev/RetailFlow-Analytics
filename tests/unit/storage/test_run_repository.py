"""Tests for report-run repository lifecycle and filtering."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from retailflow.storage import Database, RunRepository, RunStatus


def _repository(tmp_path: Path) -> RunRepository:
    database = Database(f"sqlite:///{tmp_path / 'runs.sqlite3'}")
    database.create_tables()
    return RunRepository(database)


def _create(
    repository: RunRepository,
    started_at: datetime,
    *,
    period_start: date = date(2025, 1, 1),
    period_end: date = date(2025, 1, 31),
):
    return repository.create_run(
        reporting_period_start=period_start,
        reporting_period_end=period_end,
        source_filenames={"orders": "orders.csv"},
        source_row_counts={"orders": 100},
        configuration_snapshot={"currency": "EUR", "secret": "remove-me"},
        application_version="0.1.0",
        started_at=started_at,
    )


def test_successful_run_lifecycle_and_report_path_update(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    started = datetime(2025, 1, 2, 10, tzinfo=UTC)
    run = _create(repository, started)
    assert run.status is RunStatus.PENDING
    assert repository.mark_running(run.run_id).status is RunStatus.RUNNING
    report = tmp_path / "report.xlsx"
    report.write_bytes(b"workbook")

    completed = repository.mark_completed(
        run.run_id,
        completed_at=started + timedelta(seconds=3),
        processed_row_count=95,
        excluded_row_count=5,
        warning_count=2,
        error_count=1,
        report_path=report,
        report_filename=report.name,
        report_size=report.stat().st_size,
        duration_seconds=3.0,
    )

    assert completed.status is RunStatus.COMPLETED_WITH_WARNINGS
    assert completed.processed_row_count == 95
    relocated = tmp_path / "relocated.xlsx"
    relocated.write_bytes(b"new workbook")
    updated = repository.update_report_path(run.run_id, relocated)
    assert updated.report_filename == "relocated.xlsx"
    assert repository.delete_run_metadata(run.run_id)
    assert repository.get_run(run.run_id) is None
    assert report.exists()


def test_failed_run_lifecycle(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    started = datetime(2025, 1, 2, 10, tzinfo=UTC)
    run = _create(repository, started)

    failed = repository.mark_failed(
        run.run_id,
        failure_summary="Workbook could not be written.",
        completed_at=started + timedelta(seconds=1),
        duration_seconds=1.0,
        error_count=1,
    )

    assert failed.status is RunStatus.FAILED
    assert failed.failure_summary == "Workbook could not be written."
    assert failed.report_path is None


def test_run_ids_are_unique_and_list_is_newest_first(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    morning = datetime(2025, 1, 2, 9, tzinfo=UTC)
    first = _create(repository, morning)
    second = _create(repository, morning + timedelta(hours=1))

    records = repository.list_runs()

    assert first.run_id == "RUN-20250102-001"
    assert second.run_id == "RUN-20250102-002"
    assert [record.run_id for record in records] == [second.run_id, first.run_id]


def test_concurrent_sqlite_run_ids_remain_unique(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    started = datetime(2025, 1, 3, 9, tzinfo=UTC)

    with ThreadPoolExecutor(max_workers=4) as executor:
        records = tuple(executor.map(lambda _: _create(repository, started), range(8)))

    assert len({record.run_id for record in records}) == 8
    assert {record.run_id for record in records} == {
        f"RUN-20250103-{sequence:03d}" for sequence in range(1, 9)
    }


def test_list_filters_status_period_and_started_date(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    january = _create(repository, datetime(2025, 1, 2, tzinfo=UTC))
    repository.mark_failed(
        january.run_id,
        failure_summary="Failed",
        completed_at=datetime(2025, 1, 2, 1, tzinfo=UTC),
        duration_seconds=1,
    )
    _create(
        repository,
        datetime(2025, 2, 2, tzinfo=UTC),
        period_start=date(2025, 2, 1),
        period_end=date(2025, 2, 28),
    )

    records = repository.list_runs(
        statuses=(RunStatus.FAILED,),
        reporting_period_start=date(2025, 1, 15),
        reporting_period_end=date(2025, 1, 20),
        started_from=datetime(2025, 1, 1, tzinfo=UTC),
        started_to=datetime(2025, 1, 31, 23, 59, tzinfo=UTC),
    )

    assert [record.run_id for record in records] == [january.run_id]
    assert "remove-me" not in str(records[0].configuration_snapshot)
