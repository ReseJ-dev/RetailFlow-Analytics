"""RetailFlow Analytics Overview page."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from app.components.empty_state import render_empty_state
from app.components.header import render_page_header
from app.components.layout import navigate_and_rerun
from app.components.metric_card import render_metric_card
from app.state import (
    ApplicationStatus,
    AppPage,
    LastReportSummary,
    SessionState,
    StateKey,
    has_unsaved_temporary_state,
    reset_temporary_state,
)


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
        generated_at = (
            datetime.fromtimestamp(path.stat().st_mtime)
            if path and path.exists()
            else datetime.now()
        )
    return LastReportSummary(
        reporting_period=str(state[StateKey.SELECTED_REPORTING_PERIOD.value] or "Not recorded"),
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


def _render_how_it_works() -> None:
    st.subheader("How it works")
    steps = (
        ("1", "Upload files", "Add the source files needed for your reporting period."),
        ("2", "Review data quality", "Resolve mappings and review warnings before processing."),
        ("3", "Generate analytics", "Build consistent sales, returns, and inventory metrics."),
        ("4", "Download Excel report", "Receive a polished workbook for management review."),
    )
    for column, (number, title, description) in zip(st.columns(4), steps, strict=True):
        with column:
            st.markdown(f"### {number}. {title}")
            st.write(description)


def _render_supported_sources() -> None:
    st.subheader("Supported data sources")
    sources = (
        ("CSV", "Available", "Upload comma-separated business data."),
        ("Excel", "Available", "Upload XLSX workbooks and select readable worksheets."),
        ("REST API", "Planned", "API connections will be added in a future release."),
        ("SQLite", "Planned", "Direct database connections are not enabled yet."),
    )
    for column, (name, status, description) in zip(st.columns(4), sources, strict=True):
        with column:
            st.markdown(f"### {name}")
            st.caption(status.upper())
            st.write(description)


def _render_last_report(state: SessionState) -> None:
    st.subheader("Last report")
    report = _coerce_last_report(state)
    if report is None:
        render_empty_state(
            "No report history yet",
            "No reports have been generated yet. Start with demo data or upload your own "
            "business files.",
        )
        return
    columns = st.columns(4)
    with columns[0]:
        render_metric_card("Reporting period", report.reporting_period)
    with columns[1]:
        render_metric_card("Orders processed", report.orders_processed)
    with columns[2]:
        render_metric_card("Products analysed", report.products_analysed)
    with columns[3]:
        render_metric_card("Warnings", report.warnings)
    st.write(f"**Status:** {report.status.value}")
    st.write(f"**Report file:** {report.filename}")
    st.write(f"**Generated:** {_format_datetime(report.generated_at)}")
    download_data = _report_download_data(report)
    download_column, details_column, _ = st.columns([1, 1, 3])
    download_column.download_button(
        "Download Report",
        data=download_data or b"",
        file_name=report.filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        disabled=download_data is None,
    )
    if details_column.button("View Run Details"):
        navigate_and_rerun(state, AppPage.RUN_HISTORY)


def render_overview(state: SessionState) -> None:
    """Render the complete Overview page without running data workflows."""
    render_page_header(
        page_title="Overview",
        description="Prepare reliable management reporting from your retail data.",
        reporting_period=state[StateKey.SELECTED_REPORTING_PERIOD.value],
        last_successful_run=state[StateKey.LAST_SUCCESSFUL_RUN.value],
        status=state[StateKey.APPLICATION_STATUS.value],
    )
    st.markdown("## Automate your weekly sales reporting")
    st.write(
        "Upload your sales, product, inventory and returns files. RetailFlow will "
        "validate the data and create a complete Excel management report."
    )
    if st.button("Start New Report", type="primary"):
        _begin_new_report(state)
    _render_new_report_confirmation(state)
    st.divider()
    _render_how_it_works()
    st.divider()
    _render_supported_sources()
    st.divider()
    _render_last_report(state)


__all__ = ["render_overview"]
