"""Presentation of a successfully generated management report."""

from __future__ import annotations

from collections.abc import Mapping

import streamlit as st

from app.components.layout import navigate_and_rerun
from app.components.ui import StatusVariant, section_header, status_badge
from app.services.report_service import (
    ReportRequest,
    ReportServiceError,
    ReportServiceResult,
    read_generated_report,
)
from app.state import AppPage, SessionState, StateKey, reset_temporary_state

_EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_OPTIONAL_WORKSHEETS = {
    "04_Inventory": "Inventory",
    "05_Returns": "Returns",
    "06_Data_Quality": "Data Quality",
    "07_Processed_Data": "Processed Data",
}


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _saved_request(state: SessionState) -> ReportRequest | None:
    settings = state[StateKey.REPORT_SETTINGS.value]
    request = settings.get("generation") if isinstance(settings, Mapping) else None
    return request if isinstance(request, ReportRequest) else None


def _included_sections(state: SessionState, result: ReportServiceResult) -> tuple[str, ...]:
    rows = result.statistics.rows_by_worksheet
    sections = [
        label for worksheet, label in _OPTIONAL_WORKSHEETS.items() if worksheet in rows
    ]
    request = _saved_request(state)
    if request is not None and request.include_recommendations:
        sections.append("Management Recommendations")
    return tuple(sections)


def render_report_result(state: SessionState, result: ReportServiceResult) -> None:
    """Render verified report metadata, downloads, and workflow navigation."""
    section_header(
        "Report generated",
        "The workbook was saved, verified, and recorded in Run History.",
    )
    status_badge("Generation completed", StatusVariant.SUCCESS)
    first_row = st.columns(4)
    first_row[0].metric("Report filename", result.report_path.name)
    first_row[1].metric("Run ID", result.report_id)
    first_row[2].metric("Generated", result.generated_at.astimezone().strftime("%d %b %Y, %H:%M"))
    first_row[3].metric("File size", _format_size(result.file_size))
    second_row = st.columns(4)
    second_row[0].metric("Generation duration", f"{result.generation_seconds:.2f} s")
    second_row[1].metric("Processed rows", f"{result.statistics.processed_order_rows:,}")
    second_row[2].metric("Excluded rows", f"{result.statistics.excluded_rows:,}")
    second_row[3].metric("Warnings", f"{result.warning_count:,}")
    sections = _included_sections(state, result)
    st.caption(
        "Optional sections included: "
        + (", ".join(sections) if sections else "Core worksheets only")
    )

    report_bytes: bytes | None
    try:
        report_bytes = read_generated_report(result)
    except ReportServiceError as error:
        report_bytes = None
        st.error(error.message)
    download_report, download_quality = st.columns(2)
    download_report.download_button(
        "Download Excel Report",
        data=report_bytes or b"",
        file_name=result.report_path.name,
        mime=_EXCEL_MIME,
        disabled=report_bytes is None,
        width="stretch",
    )
    download_quality.download_button(
        "Download Data Quality Report",
        data=result.quality_report,
        file_name="data_quality_report.xlsx",
        mime=_EXCEL_MIME,
        width="stretch",
    )
    history, dashboard, new_report = st.columns(3)
    if history.button("View Run History", width="stretch"):
        navigate_and_rerun(state, AppPage.RUN_HISTORY)
    if dashboard.button("View Dashboard", width="stretch"):
        navigate_and_rerun(state, AppPage.DASHBOARD)
    if new_report.button("Start New Report", width="stretch"):
        reset_temporary_state(state)
        navigate_and_rerun(state, AppPage.UPLOAD_DATA)


__all__ = ["render_report_result"]
