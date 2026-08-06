"""Data Quality workflow page."""

from collections.abc import Mapping

import streamlit as st

from app.components.issue_group import render_issue_groups
from app.components.issue_table import render_issue_table
from app.components.layout import navigate_and_rerun
from app.components.processing_progress import create_processing_progress
from app.components.quality_summary import render_quality_summary
from app.components.ui import StatusVariant, callout, empty_state, page_header, section_header
from app.services.processing_service import (
    build_quality_summary,
    combined_validation_result,
    generate_quality_report,
    group_issues,
    has_blocking_structural_errors,
    issue_identifier,
    run_processing,
)
from app.state import ApplicationStatus, AppPage, SessionState, StateKey
from retailflow.common.exceptions import RetailFlowError
from retailflow.models import ProcessingResult
from retailflow.validation import CombinedValidationResult, ValidationSeverity


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


def _review_state(
    state: SessionState,
    result: ProcessingResult,
) -> tuple[bool, bool, bool, bool]:
    structural_blocker = has_blocking_structural_errors(result)
    warnings_present = any(
        issue.severity is ValidationSeverity.WARNING for issue in result.validation_issues
    )
    invalid_issues = [issue for issue in result.validation_issues if not issue.row_can_continue]
    actions = _actions(state)
    exclusions_recorded = all(
        issue_identifier(issue, occurrence) in actions
        for occurrence, issue in enumerate(result.validation_issues)
        if not issue.row_can_continue
    )
    warnings_confirmed = bool(state[StateKey.WARNINGS_CONFIRMED.value]) or not warnings_present
    may_continue = (
        not structural_blocker
        and warnings_confirmed
        and (not invalid_issues or exclusions_recorded)
    )
    return structural_blocker, warnings_present, exclusions_recorded, may_continue


def _render_continuation_status(
    *,
    structural_blocker: bool,
    warnings_present: bool,
    warnings_confirmed: bool,
    exclusions_recorded: bool,
    invalid_issues_present: bool,
) -> None:
    if structural_blocker:
        callout(
            "Dashboard unavailable — blocking structural errors",
            "Correct the source files or column mappings and validate again. "
            "Dataset-level blocking errors cannot be bypassed or excluded.",
            StatusVariant.ERROR,
        )
    elif invalid_issues_present and not exclusions_recorded:
        callout(
            "Dashboard unavailable — exclusions required",
            "Mark invalid rows as excluded before continuing. Reviewable warnings remain "
            "separate from these invalid rows.",
            StatusVariant.WARNING,
        )
    elif warnings_present and not warnings_confirmed:
        callout(
            "Dashboard unavailable — warning confirmation required",
            "Review the warning rows and explicitly confirm them before continuing.",
            StatusVariant.WARNING,
        )
    else:
        callout(
            "Dashboard available",
            "Blocking checks and required review decisions are complete. You may continue.",
            StatusVariant.SUCCESS,
        )


def _render_review_actions(state: SessionState, result: ProcessingResult) -> None:
    section_header(
        "Review decision",
        "Blocking errors require source correction; warnings may continue only after review.",
    )
    structural_blocker, warnings_present, exclusions_recorded, may_continue = _review_state(
        state, result
    )
    invalid_issues = [issue for issue in result.validation_issues if not issue.row_can_continue]
    if warnings_present:
        st.checkbox(
            "I reviewed the warnings and confirm that processing may continue.",
            key=StateKey.WARNINGS_CONFIRMED.value,
        )
    warnings_confirmed = bool(state[StateKey.WARNINGS_CONFIRMED.value]) or not warnings_present
    _render_continuation_status(
        structural_blocker=structural_blocker,
        warnings_present=warnings_present,
        warnings_confirmed=warnings_confirmed,
        exclusions_recorded=exclusions_recorded,
        invalid_issues_present=bool(invalid_issues),
    )
    columns = st.columns(4)
    if columns[0].button(
        "Exclude Invalid Rows",
        disabled=structural_blocker or not invalid_issues,
        help=(
            "Structural errors must be corrected in the source data."
            if structural_blocker
            else (
                "No invalid row-level issues require exclusion."
                if not invalid_issues
                else "Record blocking row-level issues as excluded from processing."
            )
        ),
        width="stretch",
    ):
        _mark_excluded_rows(state, result)
    if columns[1].button(
        "Continue to Dashboard",
        type="primary",
        disabled=not may_continue,
        help=(
            "Complete the review requirements described above before continuing."
            if not may_continue
            else "Open analytics using the reviewed processing result."
        ),
        width="stretch",
    ):
        _continue_to_dashboard(state, result)
    report_bytes = generate_quality_report(
        result,
        actions=_actions(state),
        import_settings=_import_settings(state),
    )
    columns[2].download_button(
        "Download Error Report",
        data=report_bytes,
        file_name="data_quality_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        help="Includes summary, detailed issues, and excluded rows when export is enabled.",
    )
    if columns[3].button("Return to Upload", width="stretch"):
        navigate_and_rerun(state, AppPage.UPLOAD_DATA)
    st.caption(
        "The Excel error report preserves issue-level source traceability and includes the "
        "Excluded Rows worksheet when allowed by import settings."
    )


def _validation_result(
    state: SessionState,
    processing: ProcessingResult,
) -> CombinedValidationResult:
    value = state[StateKey.VALIDATION_RESULT.value]
    return (
        value
        if isinstance(value, CombinedValidationResult)
        else combined_validation_result(processing)
    )


def _blocking_error_count(result: ProcessingResult) -> int:
    return sum(
        issue.severity is ValidationSeverity.ERROR
        and issue.row_number is None
        and not issue.row_can_continue
        for issue in result.validation_issues
    )


def _render_validated_result(state: SessionState, result: ProcessingResult) -> None:
    validation = _validation_result(state, result)
    warning_rows = sum(item.warning_row_count for item in validation.dataset_results)
    render_quality_summary(
        build_quality_summary(result),
        clean_rows=validation.valid_row_count,
        warning_rows=warning_rows,
        blocking_errors=_blocking_error_count(result),
    )
    st.divider()
    render_issue_groups(group_issues(result.validation_issues))
    st.divider()
    render_issue_table(result.validation_issues, _actions(state))
    st.divider()
    _render_review_actions(state, result)


def render_data_quality(state: SessionState) -> None:
    """Run validation only on request and render filtered saved results."""
    page_header(
        "Data Quality",
        "Review data health, source-level issues, exclusions, and continuation readiness.",
    )
    result_value = state[StateKey.PROCESSING_RESULT.value]
    if not isinstance(result_value, ProcessingResult):
        empty_state(
            "Validation required",
            "No validated dataset is available. Upload the required sources, then start "
            "validation to create a quality review.",
        )
        loaded = state[StateKey.LOADED_DATASETS.value]
        action_columns = st.columns([1, 1, 3])
        if (
            isinstance(loaded, Mapping)
            and loaded
            and action_columns[0].button("Start Validation", type="primary")
        ):
            _run_validation(state)
        if action_columns[1].button("Return to Upload"):
            navigate_and_rerun(state, AppPage.UPLOAD_DATA)
        return
    _render_validated_result(state, result_value)


__all__ = ["render_data_quality"]
