"""RetailFlow Analytics product home screen."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

import streamlit as st

from app.components.layout import navigate_and_rerun
from app.components.ui import (
    ActionSpec,
    StatusVariant,
    action_bar,
    data_source_status,
    information_card,
    page_header,
    section_header,
    status_badge,
)
from app.services.processing_service import build_quality_summary
from app.services.report_service import ReportPrerequisites, check_report_prerequisites
from app.state import (
    ApplicationStatus,
    AppPage,
    LastReportSummary,
    SessionState,
    StateKey,
    has_unsaved_temporary_state,
    reset_temporary_state,
)
from retailflow.models import ProcessingResult

_OVERVIEW_DESCRIPTION = (
    "Prepare validated retail management reports from sales, product, inventory, and returns data."
)
_WORKFLOW_TITLES = (
    "Upload Data",
    "Review Quality",
    "Analyse Performance",
    "Generate Report",
)


class WorkflowViewState(StrEnum):
    """Presentation-only states for the Overview workflow."""

    COMPLETED = "Completed"
    CURRENT = "Current"
    AVAILABLE = "Available"
    UNAVAILABLE = "Unavailable"


@dataclass(frozen=True, slots=True)
class WorkflowStepView:
    """One compact workflow step shown on the Overview page."""

    title: str
    description: str
    state: WorkflowViewState


_WORKFLOW_VARIANTS = {
    WorkflowViewState.COMPLETED: StatusVariant.SUCCESS,
    WorkflowViewState.CURRENT: StatusVariant.WARNING,
    WorkflowViewState.AVAILABLE: StatusVariant.INFORMATION,
    WorkflowViewState.UNAVAILABLE: StatusVariant.NEUTRAL,
}


def _format_datetime(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _count_warnings(processing_result: object) -> int:
    issues = getattr(processing_result, "validation_issues", ())
    return sum(
        1 for issue in issues if str(getattr(issue, "severity", "")).casefold().endswith("warning")
    )


def _coerce_last_report(state: SessionState) -> LastReportSummary | None:
    report = state[StateKey.GENERATED_REPORT.value]
    if report is None:
        return None
    if isinstance(report, LastReportSummary):
        return report
    path_value = getattr(report, "report_path", None)
    path = Path(path_value) if path_value is not None else None
    statistics = getattr(report, "statistics", None)
    processing = state[StateKey.PROCESSING_RESULT.value]
    generated_at = state[StateKey.LAST_SUCCESSFUL_RUN.value]
    if not isinstance(generated_at, datetime):
        try:
            generated_at = datetime.fromtimestamp(path.stat().st_mtime) if path else datetime.now()
        except OSError:
            generated_at = datetime.now()
    return LastReportSummary(
        reporting_period=str(
            state[StateKey.SELECTED_REPORTING_PERIOD.value] or "No reporting period selected"
        ),
        orders_processed=int(getattr(statistics, "processed_order_rows", 0)),
        products_analysed=len(getattr(processing, "products", ())),
        warnings=_count_warnings(processing),
        status=ApplicationStatus.REPORT_GENERATED,
        filename=path.name if path is not None else "RetailFlow report.xlsx",
        generated_at=generated_at,
        report_path=path,
    )


def _report_download_data(report: LastReportSummary) -> bytes | None:
    if report.report_bytes is not None:
        return report.report_bytes
    if report.report_path is None:
        return None
    try:
        return report.report_path.read_bytes()
    except OSError:
        return None


def _begin_new_report(state: SessionState) -> None:
    if has_unsaved_temporary_state(state):
        state[StateKey.CONFIRM_NEW_REPORT.value] = True
        return
    reset_temporary_state(state)
    navigate_and_rerun(state, AppPage.UPLOAD_DATA)


def _render_new_report_confirmation(state: SessionState) -> None:
    if not state[StateKey.CONFIRM_NEW_REPORT.value]:
        return
    st.warning(
        "Starting a new report will clear the files and temporary results in this workspace. "
        "Your last generated report will remain available."
    )
    confirm_column, cancel_column, _ = st.columns([1, 1, 3])
    if confirm_column.button("Confirm new report", type="primary"):
        reset_temporary_state(state)
        navigate_and_rerun(state, AppPage.UPLOAD_DATA)
    if cancel_column.button("Keep current work"):
        state[StateKey.CONFIRM_NEW_REPORT.value] = False
        st.rerun()


def _has_loaded_sources(state: SessionState) -> bool:
    loaded = state[StateKey.LOADED_DATASETS.value]
    return isinstance(loaded, Mapping) and bool(loaded)


def _is_current_report_complete(
    state: SessionState,
    report: LastReportSummary | None,
) -> bool:
    """Distinguish the active result from a report retained from a previous workflow."""
    processing = state[StateKey.PROCESSING_RESULT.value]
    status = state[StateKey.APPLICATION_STATUS.value]
    return (
        report is not None
        and isinstance(processing, ProcessingResult)
        and status == ApplicationStatus.REPORT_GENERATED
    )


def _workflow_steps(
    state: SessionState,
    prerequisite: ReportPrerequisites,
    *,
    current_report_complete: bool,
) -> tuple[WorkflowStepView, ...]:
    descriptions = (
        "Add the required orders, products, inventory, and returns datasets.",
        "Validate mappings, exclusions, warnings, and data relationships.",
        "Open the dashboard to prepare sales, returns, and inventory analytics.",
        "Configure and create the Excel management workbook.",
    )
    if current_report_complete:
        states = (WorkflowViewState.COMPLETED,) * 4
    elif prerequisite.ready:
        states = (
            WorkflowViewState.COMPLETED,
            WorkflowViewState.COMPLETED,
            WorkflowViewState.COMPLETED,
            WorkflowViewState.AVAILABLE,
        )
    elif prerequisite.required_page == AppPage.DASHBOARD.value:
        states = (
            WorkflowViewState.COMPLETED,
            WorkflowViewState.COMPLETED,
            WorkflowViewState.AVAILABLE,
            WorkflowViewState.UNAVAILABLE,
        )
    elif prerequisite.required_page == AppPage.DATA_QUALITY.value or _has_loaded_sources(state):
        states = (
            WorkflowViewState.COMPLETED,
            WorkflowViewState.CURRENT,
            WorkflowViewState.UNAVAILABLE,
            WorkflowViewState.UNAVAILABLE,
        )
    else:
        states = (
            WorkflowViewState.CURRENT,
            WorkflowViewState.UNAVAILABLE,
            WorkflowViewState.UNAVAILABLE,
            WorkflowViewState.UNAVAILABLE,
        )
    return tuple(
        WorkflowStepView(title, description, state_value)
        for title, description, state_value in zip(
            _WORKFLOW_TITLES, descriptions, states, strict=True
        )
    )


def _render_workflow(steps: tuple[WorkflowStepView, ...]) -> None:
    section_header(
        "Workflow progress",
        "Each stage becomes available after its required review is complete.",
    )
    for column, step in zip(st.columns(4), steps, strict=True):
        with column, st.container(border=True):
            st.markdown(f"**{step.title}**")
            status_badge(
                step.state.value,
                _WORKFLOW_VARIANTS[step.state],
                accessible_label=f"{step.title}: {step.state.value}",
            )
            st.caption(step.description)


def _source_summary(state: SessionState) -> tuple[str, str]:
    loaded = state[StateKey.LOADED_DATASETS.value]
    count = len(loaded) if isinstance(loaded, Mapping) else 0
    period = state[StateKey.SELECTED_REPORTING_PERIOD.value]
    if not count:
        return "No sources loaded", "Upload the required source files to begin."
    period_text = f"Reporting period: {period}" if period else "No reporting period selected"
    label = "dataset" if count == 1 else "datasets"
    return f"{count} {label} loaded", period_text


def _quality_summary(
    processing: ProcessingResult | None,
    prerequisite: ReportPrerequisites,
) -> tuple[str, str]:
    if processing is None:
        return "Validation not started", "Upload the required source files to begin."
    summary = build_quality_summary(processing)
    if prerequisite.required_page == AppPage.DATA_QUALITY.value:
        return (
            f"{summary.quality_score:.1f}% rule-based score",
            f"Review {summary.errors} errors and {summary.warnings} warnings before continuing.",
        )
    return (
        "Quality review complete",
        f"{summary.source_rows:,} source rows processed; {summary.excluded_rows:,} excluded.",
    )


def _workflow_summary(
    state: SessionState,
    prerequisite: ReportPrerequisites,
    *,
    current_report_complete: bool,
) -> tuple[str, str]:
    if state[StateKey.APPLICATION_STATUS.value] == ApplicationStatus.FAILED:
        return "Workflow needs attention", "Review the latest error and retry the current step."
    if current_report_complete:
        return "Report completed", "Open the latest run or start another reporting workflow."
    if prerequisite.ready:
        return "Ready to generate report", "Configure the workbook and create the final report."
    if prerequisite.required_page == AppPage.DASHBOARD.value:
        return "Analytics available", "Open Dashboard to prepare performance metrics."
    if prerequisite.required_page == AppPage.DATA_QUALITY.value:
        return "Quality review required", "Resolve blocking issues and confirm valid warnings."
    if _has_loaded_sources(state):
        return "Sources ready for validation", "Continue to Data Quality to validate the uploads."
    return "Upload required source files to begin", "Start New Report to open the upload workflow."


def _render_operational_summary(
    state: SessionState,
    report: LastReportSummary | None,
    prerequisite: ReportPrerequisites,
) -> None:
    section_header(
        "Operational summary",
        "Current workspace readiness and the next useful action.",
    )
    processing_value = state[StateKey.PROCESSING_RESULT.value]
    processing = processing_value if isinstance(processing_value, ProcessingResult) else None
    current_report_complete = _is_current_report_complete(state, report)
    source_title, source_body = _source_summary(state)
    quality_title, quality_body = _quality_summary(processing, prerequisite)
    workflow_title, workflow_body = _workflow_summary(
        state,
        prerequisite,
        current_report_complete=current_report_complete,
    )
    report_title = report.filename if report is not None else "No completed report is available"
    report_body = (
        f"Generated {_format_datetime(report.generated_at)} · {report.reporting_period}"
        if report is not None
        else "Complete validation and analytics to create a management report."
    )
    cards = (
        ("DATA SOURCES", source_title, source_body),
        ("DATA QUALITY", quality_title, quality_body),
        ("LATEST REPORT", report_title, report_body),
        ("WORKFLOW STATUS", workflow_title, workflow_body),
    )
    for column, (label, title, body) in zip(st.columns(4), cards, strict=True):
        with column:
            information_card(title, body, label=label)


def _render_how_it_works() -> None:
    section_header("How it works", "Four compact steps from raw sources to management output.")
    steps = (
        ("Upload", "Add source data for the reporting period."),
        ("Validate", "Review mappings, errors, warnings, and exclusions."),
        ("Analyse", "Prepare consistent sales, returns, and inventory metrics."),
        ("Report", "Create and download the Excel management workbook."),
    )
    for column, (title, description) in zip(st.columns(4), steps, strict=True):
        with column:
            information_card(title, description, label="WORKFLOW STEP")


def _render_supported_capabilities() -> None:
    section_header(
        "Supported capabilities",
        "Upload sources and local application storage serve different purposes.",
    )
    capabilities = (
        (
            "CSV",
            "Source upload",
            StatusVariant.SUCCESS,
            "Upload comma-separated source datasets.",
        ),
        (
            "Excel",
            "Source upload",
            StatusVariant.SUCCESS,
            "Upload XLSX workbooks and select readable worksheets.",
        ),
        (
            "REST API",
            "Optional source",
            StatusVariant.INFORMATION,
            "Load datasets from an authenticated API connection.",
        ),
        (
            "SQLite",
            "Local storage",
            StatusVariant.NEUTRAL,
            "Stores local run-history metadata; it is not an upload source.",
        ),
    )
    for column, (name, status, variant, detail) in zip(st.columns(4), capabilities, strict=True):
        with column:
            data_source_status(name, status, variant=variant, detail=detail)


def _render_report_download(report: LastReportSummary | None) -> None:
    if report is None:
        return
    download_data = _report_download_data(report)
    st.download_button(
        "Download Report",
        data=download_data or b"",
        file_name=report.filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        disabled=download_data is None,
        help=(
            None
            if download_data is not None
            else "The run metadata is available, but the report file cannot be read."
        ),
    )


def render_overview(state: SessionState) -> None:
    """Render the operational Overview without running data workflows."""
    report = _coerce_last_report(state)
    prerequisite = check_report_prerequisites(state)
    current_report_complete = _is_current_report_complete(state, report)

    page_header("Overview", _OVERVIEW_DESCRIPTION)
    actions = [
        ActionSpec(
            "overview_start_new_report",
            "Start New Report",
            button_type="primary",
            icon=":material/note_add:",
        )
    ]
    if report is not None:
        actions.append(
            ActionSpec(
                "overview_open_latest_run",
                "Open Latest Run",
                icon=":material/history:",
            )
        )
    selected_action = action_bar(actions, accessible_label="Overview actions")
    if selected_action == "overview_start_new_report":
        _begin_new_report(state)
    elif selected_action == "overview_open_latest_run":
        navigate_and_rerun(state, AppPage.RUN_HISTORY)
    _render_new_report_confirmation(state)

    st.divider()
    _render_workflow(
        _workflow_steps(
            state,
            prerequisite,
            current_report_complete=current_report_complete,
        )
    )
    st.divider()
    _render_operational_summary(state, report, prerequisite)
    _render_report_download(report)
    st.divider()
    _render_how_it_works()
    st.divider()
    _render_supported_capabilities()


__all__ = ["render_overview"]
