"""Data Quality workflow page."""

from collections.abc import Mapping

import streamlit as st

from app.components.empty_state import render_empty_state
from app.components.header import render_page_header
from app.components.issue_group import render_issue_groups
from app.components.issue_table import render_issue_table
from app.components.layout import navigate_and_rerun
from app.components.processing_progress import create_processing_progress
from app.components.quality_summary import render_quality_summary
from app.services.processing_service import (
    build_quality_summary,
    generate_quality_report,
    group_issues,
    has_blocking_structural_errors,
    issue_identifier,
    run_processing,
)
from app.state import ApplicationStatus, AppPage, SessionState, StateKey
from retailflow.common.exceptions import RetailFlowError
from retailflow.models import ProcessingResult
from retailflow.validation import ValidationSeverity


def _actions(state: SessionState) -> dict[str, str]:
    value = state[StateKey.ISSUE_ACTIONS.value]
    return value if isinstance(value, dict) else {}


def _import_settings(state: SessionState) -> Mapping[str, object]:
    value = state[StateKey.IMPORT_SETTINGS.value]
    return value if isinstance(value, Mapping) else {}


def _run_validation(state: SessionState) -> None:
    callback = create_processing_progress()
    try:
        run_processing(state, progress_callback=callback)
    except RetailFlowError as error:
        st.error(error.message)
        return
    st.success("Validation and processing completed successfully.")
    st.rerun()


def _mark_excluded_rows(state: SessionState, result: ProcessingResult) -> None:
    actions = _actions(state)
    for occurrence, issue in enumerate(result.validation_issues):
        if not issue.row_can_continue:
            actions[issue_identifier(issue, occurrence)] = "Excluded from processing"
    state[StateKey.ISSUE_ACTIONS.value] = actions
    st.success("Invalid rows have been marked as excluded from processing.")
    st.rerun()


def _continue_to_dashboard(state: SessionState, result: ProcessingResult) -> None:
    actions = _actions(state)
    for occurrence, issue in enumerate(result.validation_issues):
        identifier = issue_identifier(issue, occurrence)
        if issue.severity is ValidationSeverity.WARNING:
            actions[identifier] = "Accepted with warning"
        elif not issue.row_can_continue:
            actions.setdefault(identifier, "Excluded from processing")
    state[StateKey.ISSUE_ACTIONS.value] = actions
    state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.READY
    navigate_and_rerun(state, AppPage.DASHBOARD)


def _render_review_actions(state: SessionState, result: ProcessingResult) -> None:
    st.subheader("Review decision")
    structural_blocker = has_blocking_structural_errors(result)
    warnings = [
        issue for issue in result.validation_issues if issue.severity is ValidationSeverity.WARNING
    ]
    invalid_issues = [issue for issue in result.validation_issues if not issue.row_can_continue]
    actions = _actions(state)
    exclusions_recorded = all(
        issue_identifier(issue, occurrence) in actions
        for occurrence, issue in enumerate(result.validation_issues)
        if not issue.row_can_continue
    )
    if structural_blocker:
        st.error(
            "Blocking structural errors must be corrected before this dataset can continue. "
            "Return to Upload Data and update the source files or column mappings."
        )
    if warnings:
        st.checkbox(
            "I reviewed the warnings and confirm that processing may continue.",
            key=StateKey.WARNINGS_CONFIRMED.value,
        )
    warnings_confirmed = bool(state[StateKey.WARNINGS_CONFIRMED.value]) or not warnings
    columns = st.columns(4)
    if columns[0].button(
        "Exclude Invalid Rows",
        disabled=structural_blocker or not invalid_issues,
        width="stretch",
    ):
        _mark_excluded_rows(state, result)
    continue_disabled = (
        structural_blocker
        or not warnings_confirmed
        or (bool(invalid_issues) and not exclusions_recorded)
    )
    if columns[1].button(
        "Continue with Warnings",
        type="primary",
        disabled=continue_disabled,
        width="stretch",
    ):
        _continue_to_dashboard(state, result)
    report_bytes = generate_quality_report(
        result,
        actions=actions,
        import_settings=_import_settings(state),
    )
    columns[2].download_button(
        "Download Error Report",
        data=report_bytes,
        file_name="data_quality_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
    if columns[3].button("Return to Upload", width="stretch"):
        navigate_and_rerun(state, AppPage.UPLOAD_DATA)


def render_data_quality(state: SessionState) -> None:
    """Run validation when requested and render the resulting quality review."""
    render_page_header(
        page_title="Data Quality",
        description=(
            "Validate source structure, transformations, and business rules before analysis."
        ),
        reporting_period=state[StateKey.SELECTED_REPORTING_PERIOD.value],
        last_successful_run=state[StateKey.LAST_SUCCESSFUL_RUN.value],
        status=state[StateKey.APPLICATION_STATUS.value],
    )
    result_value = state[StateKey.PROCESSING_RESULT.value]
    if not isinstance(result_value, ProcessingResult):
        render_empty_state(
            "Validation required",
            "No validated dataset is available. Upload and validate your source files first.",
        )
        loaded = state[StateKey.LOADED_DATASETS.value]
        if isinstance(loaded, Mapping) and loaded and st.button("Start Validation", type="primary"):
            _run_validation(state)
        if st.button("Return to Upload"):
            navigate_and_rerun(state, AppPage.UPLOAD_DATA)
        return

    render_quality_summary(build_quality_summary(result_value))
    render_issue_groups(group_issues(result_value.validation_issues))
    render_issue_table(result_value.validation_issues, _actions(state))
    _render_review_actions(state, result_value)


__all__ = ["render_data_quality"]
