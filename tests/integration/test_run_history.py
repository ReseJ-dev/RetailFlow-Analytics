"""Integration tests for report generation and persistent run history."""

from pathlib import Path

import pytest
from app.services.report_service import (
    ReportServiceError,
    generate_management_report,
)
from app.services.run_history_service import (
    MISSING_REPORT_MESSAGE,
    read_historical_report,
    report_is_available,
)
from tests.unit.app.test_report_service import _ready_state, _request

from retailflow.reporting.excel_report import ExcelReportGenerator
from retailflow.storage import Database, RunRepository, RunStatus


def _repository(tmp_path: Path) -> RunRepository:
    database = Database(f"sqlite:///{tmp_path / 'history.sqlite3'}")
    database.create_tables()
    return RunRepository(database)


def test_successful_report_is_persisted_and_downloadable(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    state = _ready_state()

    result = generate_management_report(
        state,
        _request(tmp_path / "reports"),
        run_repository=repository,
    )

    record = repository.get_run(result.report_id)
    assert record is not None
    assert record.status is RunStatus.COMPLETED
    assert record.report_filename == result.report_path.name
    assert record.report_size == result.file_size
    assert record.processed_row_count > 0
    assert read_historical_report(record) == result.report_path.read_bytes()


def test_failed_generation_is_persisted_without_losing_original_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path)
    state = _ready_state()

    def fail_generation(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("worksheet exploded")

    monkeypatch.setattr(ExcelReportGenerator, "generate", fail_generation)
    with pytest.raises(ReportServiceError) as captured:
        generate_management_report(
            state,
            _request(tmp_path / "reports"),
            run_repository=repository,
        )

    assert isinstance(captured.value.__cause__, RuntimeError)
    records = repository.list_runs()
    assert len(records) == 1
    assert records[0].status is RunStatus.FAILED
    assert records[0].failure_summary is not None
    assert "worksheet exploded" not in records[0].failure_summary


def test_missing_report_file_preserves_metadata(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    result = generate_management_report(
        _ready_state(),
        _request(tmp_path / "reports"),
        run_repository=repository,
    )
    record = repository.get_run(result.report_id)
    assert record is not None
    result.report_path.unlink()

    refreshed = repository.get_run(result.report_id)
    assert refreshed is not None
    assert not report_is_available(refreshed)
    assert read_historical_report(refreshed) is None
    assert MISSING_REPORT_MESSAGE == (
        "Run metadata is available, but the generated file can no longer be found."
    )
