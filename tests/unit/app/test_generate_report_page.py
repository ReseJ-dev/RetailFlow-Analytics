from __future__ import annotations

from pathlib import Path

from app.components.report_settings import _safe_output_location
from app.pages.generate_report import _safe_diagnostic_detail
from app.services import report_service
from app.services.report_service import ReportServiceError
from app.state import AppPage, StateKey
from streamlit.testing.v1 import AppTest

from retailflow.storage import Database, RunRepository

from .test_report_service import _ready_state, _request


def _repository(tmp_path: Path) -> RunRepository:
    database = Database(f"sqlite:///{tmp_path / 'page-history.sqlite3'}")
    database.create_tables()
    return RunRepository(database)


def test_output_location_does_not_expose_absolute_parent_directories(tmp_path: Path) -> None:
    label = _safe_output_location(tmp_path / "private" / "reports")

    assert label == "Configured application directory (reports)"
    assert str(tmp_path) not in label
    assert _safe_output_location(Path("output")) == "output"


def test_diagnostics_hide_paths_and_sensitive_values() -> None:
    safe = ReportServiceError("Failed.", technical_detail="Stage: Creating worksheets")
    path = ReportServiceError("Failed.", technical_detail="Path: /private/reports/file.xlsx")
    token = ReportServiceError("Failed.", technical_detail="API token was rejected")

    assert _safe_diagnostic_detail(safe) == "Stage: Creating worksheets"
    assert _safe_diagnostic_detail(path) is None
    assert _safe_diagnostic_detail(token) is None


def test_successful_page_rerun_does_not_generate_a_duplicate_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = _repository(tmp_path)
    monkeypatch.setattr(report_service, "get_run_repository", lambda: repository)
    ready_state = _ready_state()
    output_directory = tmp_path / "reports"
    ready_state[StateKey.REPORT_SETTINGS.value] = {
        "generation": _request(output_directory)
    }
    app = AppTest.from_file("app/main.py", default_timeout=30).run()
    for key, value in ready_state.items():
        app.session_state[key] = value
    app.session_state[StateKey.CURRENT_PAGE.value] = AppPage.GENERATE_REPORT

    app = app.run()

    assert not app.exception
    assert [heading.value for heading in app.subheader[:5]] == [
        "Report Identity",
        "Branding",
        "Included Sections",
        "Output Configuration",
        "Generation Summary",
    ]
    assert any(button.label == "Generate Excel Report" for button in app.button)
    generate = next(button for button in app.button if button.label == "Generate Excel Report")

    app = generate.click().run()

    assert not app.exception
    assert len(repository.list_runs()) == 1
    assert (output_directory / "management_report.xlsx").is_file()
    labels = [metric.label for metric in app.metric]
    assert labels[:4] == ["Report filename", "Run ID", "Generated", "File size"]
    assert any(button.label == "View Run History" for button in app.button)
    assert any(button.label == "Generate Another Report" for button in app.button)
    assert not any(button.label == "Generate Excel Report" for button in app.button)

    app = app.run()

    assert not app.exception
    assert len(repository.list_runs()) == 1
