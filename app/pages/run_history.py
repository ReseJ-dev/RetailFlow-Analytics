"""Streamlit page for persistent report-run history."""

from __future__ import annotations

from datetime import date

import streamlit as st

from app.components.empty_state import render_empty_state
from app.components.header import render_page_header
from app.services.run_history_service import (
    MISSING_REPORT_MESSAGE,
    RunHistoryFilters,
    get_run_repository,
    list_run_history,
    read_historical_report,
    run_history_dataframe,
)
from app.state import SessionState, StateKey
from retailflow.common.exceptions import RetailFlowError
from retailflow.storage import RunRecord, RunStatus

_EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _date_range(label: str, key: str) -> tuple[date | None, date | None]:
    enabled = st.checkbox(f"Filter by {label.lower()}", key=f"{key}_enabled")
    if not enabled:
        return None, None
    value: object = st.date_input(label, value=(date.today(), date.today()), key=key)
    if isinstance(value, date):
        return value, value
    if isinstance(value, (tuple, list)) and len(value) == 2:
        start, end = value
        if isinstance(start, date) and isinstance(end, date):
            return start, end
    return None, None


def _render_filters() -> RunHistoryFilters:
    status_column, period_column, started_column = st.columns(3)
    with status_column:
        status_values = st.multiselect(
            "Status",
            options=list(RunStatus),
            format_func=lambda value: value.value,
        )
    with period_column:
        period_start, period_end = _date_range("Reporting period", "history_period")
    with started_column:
        started_from, started_to = _date_range("Run date range", "history_started")
    return RunHistoryFilters(
        statuses=tuple(status_values),
        reporting_period_start=period_start,
        reporting_period_end=period_end,
        started_date_from=started_from,
        started_date_to=started_to,
    )


def _render_mapping(title: str, values: object) -> None:
    st.markdown(f"#### {title}")
    st.json(values, expanded=False)


def _render_run_details(record: RunRecord) -> None:
    st.subheader(record.run_id)
    metrics = st.columns(4)
    metrics[0].metric("Processed rows", f"{record.processed_row_count:,}")
    metrics[1].metric("Excluded rows", f"{record.excluded_row_count:,}")
    metrics[2].metric("Warnings", f"{record.warning_count:,}")
    metrics[3].metric("Errors", f"{record.error_count:,}")
    st.write(f"**Status:** {record.status.value}")
    st.write(
        "**Reporting period:** "
        f"{record.reporting_period_start:%Y-%m-%d} to "
        f"{record.reporting_period_end:%Y-%m-%d}"
    )
    st.write(f"**Application version:** {record.application_version}")
    if record.duration_seconds is not None:
        st.write(f"**Duration:** {record.duration_seconds:.2f} seconds")

    source_column, configuration_column = st.columns(2)
    with source_column:
        _render_mapping("Source files", dict(record.source_filenames))
        _render_mapping("Source row counts", dict(record.source_row_counts))
    with configuration_column:
        _render_mapping("Configuration summary", dict(record.configuration_snapshot))

    st.markdown("#### Report metadata")
    if record.failure_summary:
        st.error(record.failure_summary)
    report = read_historical_report(record)
    if report is None:
        st.info(MISSING_REPORT_MESSAGE)
    else:
        st.download_button(
            "Download Excel Report",
            data=report,
            file_name=record.report_filename or f"{record.run_id}.xlsx",
            mime=_EXCEL_MIME,
        )


def render_run_history(state: SessionState) -> None:
    """Render filterable history and details from persistent domain records."""
    render_page_header(
        page_title="Run History",
        description="Review successful and failed report-generation attempts.",
        reporting_period=state[StateKey.SELECTED_REPORTING_PERIOD.value],
        last_successful_run=state[StateKey.LAST_SUCCESSFUL_RUN.value],
        status=state[StateKey.APPLICATION_STATUS.value],
    )
    filters = _render_filters()
    try:
        records = list_run_history(get_run_repository(), filters)
    except RetailFlowError as error:
        st.error(error.message)
        return
    if not records:
        render_empty_state("No matching runs", "No saved report runs match these filters.")
        return

    st.dataframe(run_history_dataframe(records), hide_index=True, width="stretch")
    selected_id = st.selectbox("Select a run", [record.run_id for record in records])
    selected = next(record for record in records if record.run_id == selected_id)
    _render_run_details(selected)


__all__ = ["render_run_history"]
