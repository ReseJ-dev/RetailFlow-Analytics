"""Presentation of a successfully generated management report."""

from __future__ import annotations

import streamlit as st

from app.components.layout import navigate_and_rerun
from app.services.report_service import (
    ReportServiceError,
    ReportServiceResult,
    read_generated_report,
)
from app.state import AppPage, SessionState, reset_temporary_state

_EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def render_report_result(state: SessionState, result: ReportServiceResult) -> None:
    """Render result metadata, safe downloads, and workflow navigation."""
    st.success("Your Excel management report is ready.")
    first_row = st.columns(4)
    first_row[0].metric("Filename", result.report_path.name)
    first_row[1].metric("Output size", _format_size(result.file_size))
    first_row[2].metric("Generation duration", f"{result.generation_seconds:.2f} s")
    first_row[3].metric("Report ID", result.report_id)
    second_row = st.columns(3)
    second_row[0].metric("Processed rows", f"{result.statistics.processed_order_rows:,}")
    second_row[1].metric("Excluded rows", f"{result.statistics.excluded_rows:,}")
    second_row[2].metric("Warnings", f"{result.warning_count:,}")

    report_bytes: bytes | None
    try:
        report_bytes = read_generated_report(result)
    except ReportServiceError as error:
        report_bytes = None
        st.error(error.message)
    download_report, download_quality, dashboard, new_report = st.columns(4)
    download_report.download_button(
        "Download Excel Report",
        data=report_bytes or b"",
        file_name=result.report_path.name,
        mime=_EXCEL_MIME,
        disabled=report_bytes is None,
    )
    download_quality.download_button(
        "Download Data Quality Report",
        data=result.quality_report,
        file_name="data_quality_report.xlsx",
        mime=_EXCEL_MIME,
    )
    if dashboard.button("View Dashboard"):
        navigate_and_rerun(state, AppPage.DASHBOARD)
    if new_report.button("Start New Report"):
        reset_temporary_state(state)
        navigate_and_rerun(state, AppPage.UPLOAD_DATA)


__all__ = ["render_report_result"]
