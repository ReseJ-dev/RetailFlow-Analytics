from datetime import UTC, datetime

from app.pages.overview import WorkflowViewState, _source_summary, _workflow_steps
from app.services.report_service import ReportPrerequisites
from app.state import (
    ApplicationStatus,
    AppPage,
    LastReportSummary,
    StateKey,
    initialize_state,
)
from streamlit.testing.v1 import AppTest


def test_empty_workspace_explains_the_first_available_step() -> None:
    state: dict[str, object] = {}
    initialize_state(state)

    steps = _workflow_steps(
        state,
        ReportPrerequisites(False, required_page=AppPage.UPLOAD_DATA.value),
        current_report_complete=False,
    )

    assert tuple(step.state for step in steps) == (
        WorkflowViewState.CURRENT,
        WorkflowViewState.UNAVAILABLE,
        WorkflowViewState.UNAVAILABLE,
        WorkflowViewState.UNAVAILABLE,
    )


def test_workflow_marks_dashboard_available_after_quality_review() -> None:
    state: dict[str, object] = {}
    initialize_state(state)

    steps = _workflow_steps(
        state,
        ReportPrerequisites(False, required_page=AppPage.DASHBOARD.value),
        current_report_complete=False,
    )

    assert tuple(step.state for step in steps) == (
        WorkflowViewState.COMPLETED,
        WorkflowViewState.COMPLETED,
        WorkflowViewState.AVAILABLE,
        WorkflowViewState.UNAVAILABLE,
    )


def test_source_summary_uses_actionable_empty_and_period_messages() -> None:
    state: dict[str, object] = {}
    initialize_state(state)

    assert _source_summary(state) == (
        "No sources loaded",
        "Upload the required source files to begin.",
    )

    state[StateKey.LOADED_DATASETS.value] = {"orders": object()}
    assert _source_summary(state) == (
        "1 dataset loaded",
        "No reporting period selected",
    )


def test_overview_primary_action_opens_existing_upload_workflow() -> None:
    app = AppTest.from_file("app/main.py", default_timeout=10).run()

    assert not app.exception
    assert app.title[0].value == "Overview"
    assert any(
        markdown.value.startswith("Prepare validated retail management reports")
        for markdown in app.markdown
    )
    assert any(button.label == "Start New Report" for button in app.button)
    assert not any(button.label == "Open Latest Run" for button in app.button)

    start = next(button for button in app.button if button.label == "Start New Report")
    app = start.click().run()

    assert not app.exception
    assert app.title[0].value == AppPage.UPLOAD_DATA.value


def test_latest_run_action_is_only_rendered_for_a_saved_report() -> None:
    app = AppTest.from_file("app/main.py", default_timeout=10).run()
    generated_at = datetime(2026, 8, 5, 12, 30, tzinfo=UTC)
    app.session_state[StateKey.GENERATED_REPORT.value] = LastReportSummary(
        reporting_period="2026-07",
        orders_processed=120,
        products_analysed=18,
        warnings=2,
        status=ApplicationStatus.REPORT_GENERATED,
        filename="retailflow-july.xlsx",
        generated_at=generated_at,
    )
    app.session_state[StateKey.LAST_SUCCESSFUL_RUN.value] = generated_at

    app = app.run()

    assert not app.exception
    assert any(button.label == "Open Latest Run" for button in app.button)
    assert any("retailflow-july.xlsx" in markdown.value for markdown in app.markdown)
    assert any(
        "Stores local run-history metadata; it is not an upload source." in caption.value
        for caption in app.caption
    )

    open_latest = next(button for button in app.button if button.label == "Open Latest Run")
    app = open_latest.click().run()

    assert not app.exception
    assert app.title[0].value == AppPage.RUN_HISTORY.value
