"""Streamlit page for persistent report-run history."""

from __future__ import annotations

from datetime import date

import streamlit as st

from app.components.header import render_page_header
from app.components.ui import (
    StatusVariant,
    callout,
    empty_state,
    metric_card,
    section_header,
    status_badge,
)
from app.services.run_history_service import (
    MISSING_REPORT_MESSAGE,
    RunHistoryFilters,
    get_run_repository,
    list_run_history,
    read_historical_report,
    resolve_report_availability,
    run_history_dataframe,
    safe_configuration_snapshot,
    safe_failure_summary,
    safe_source_filenames,
)
from app.state import SessionState, StateKey
from retailflow.common.exceptions import RetailFlowError
from retailflow.storage import RunRecord, RunStatus

_EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_ROW_LIMIT_OPTIONS = (10, 25, 50, 100)
_STATUS_VARIANTS = {
    RunStatus.PENDING: StatusVariant.NEUTRAL,
    RunStatus.RUNNING: StatusVariant.INFORMATION,
    RunStatus.COMPLETED: StatusVariant.SUCCESS,
    RunStatus.COMPLETED_WITH_WARNINGS: StatusVariant.WARNING,
    RunStatus.FAILED: StatusVariant.ERROR,
    RunStatus.CANCELLED: StatusVariant.NEUTRAL,
}


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


def _render_filters() -> tuple[RunHistoryFilters, int]:
    section_header(
        "Find a run",
        "Filter saved metadata without changing or deleting any run records.",
    )
    search_column, status_column = st.columns(2)
    with search_column:
        run_id_query = st.text_input(
            "Search by Run ID",
            placeholder="RUN-YYYYMMDD-NNN",
        )
    with status_column:
        status_values = st.multiselect(
            "Status",
            options=list(RunStatus),
            format_func=lambda value: value.value,
        )
    period_column, started_column, limit_column = st.columns([1, 1, 0.55])
    with period_column:
        period_start, period_end = _date_range("Reporting period", "history_period")
    with started_column:
        started_from, started_to = _date_range("Run date range", "history_started")
    with limit_column:
        row_limit = st.selectbox(
            "Rows to show",
            options=_ROW_LIMIT_OPTIONS,
            index=1,
        )
    return (
        RunHistoryFilters(
            statuses=tuple(status_values),
            reporting_period_start=period_start,
            reporting_period_end=period_end,
            started_date_from=started_from,
            started_date_to=started_to,
            run_id_query=run_id_query,
        ),
        row_limit,
    )


def _render_mapping(title: str, values: object) -> None:
    st.markdown(f"#### {title}")
    st.json(values, expanded=False)


def _render_status_summary(records: tuple[RunRecord, ...]) -> None:
    counts = {status: 0 for status in RunStatus}
    for record in records:
        counts[record.status] += 1
    columns = st.columns(3)
    for index, status in enumerate(RunStatus):
        with columns[index % 3]:
            status_badge(
                f"{status.value}: {counts[status]}",
                _STATUS_VARIANTS[status],
                accessible_label=f"{status.value} runs: {counts[status]}",
            )


def _render_run_details(record: RunRecord, *, report_available: bool) -> None:
    status_badge(record.status.value, _STATUS_VARIANTS[record.status])
    metrics = st.columns(4)
    with metrics[0]:
        metric_card("Processed rows", f"{record.processed_row_count:,}")
    with metrics[1]:
        metric_card("Excluded rows", f"{record.excluded_row_count:,}")
    with metrics[2]:
        metric_card("Warnings", f"{record.warning_count:,}")
    with metrics[3]:
        metric_card("Errors", f"{record.error_count:,}")
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
        _render_mapping("Source files", safe_source_filenames(record))
        _render_mapping("Source row counts", dict(record.source_row_counts))
    with configuration_column:
        _render_mapping("Configuration summary", safe_configuration_snapshot(record))

    st.markdown("#### Report metadata")
    status_columns = st.columns(2)
    with status_columns[0]:
        status_badge("Metadata available", StatusVariant.SUCCESS)
    with status_columns[1]:
        status_badge(
            "Output file available" if report_available else "Output file unavailable",
            StatusVariant.SUCCESS if report_available else StatusVariant.WARNING,
        )
    failure_summary = safe_failure_summary(record)
    if failure_summary:
        callout("Run failed", failure_summary, StatusVariant.ERROR)
    report = read_historical_report(record, known_available=report_available)
    if report is None:
        callout("Workbook unavailable", MISSING_REPORT_MESSAGE, StatusVariant.WARNING)
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
    filters, row_limit = _render_filters()
    try:
        records = list_run_history(get_run_repository(), filters)
    except RetailFlowError as error:
        st.error(error.message)
        return
    if not records:
        empty_state(
            "No matching runs",
            "No saved report runs match these filters. Adjust the filters or "
            "generate a new report.",
        )
        return

    section_header(
        "Run status",
        "Every lifecycle state remains visible as text as well as colour.",
    )
    _render_status_summary(records)

    visible_records = records[:row_limit]
    availability = resolve_report_availability(visible_records)
    section_header(
        "Saved runs",
        "Newest runs appear first. Select any visible run to inspect its saved metadata.",
    )
    st.caption(f"Showing {len(visible_records):,} of {len(records):,} matching runs.")
    st.dataframe(
        run_history_dataframe(visible_records, availability),
        hide_index=True,
        width="stretch",
        column_config={
            "Started At": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            "Source Rows": st.column_config.NumberColumn(format="localized"),
            "Excluded Rows": st.column_config.NumberColumn(format="localized"),
            "Warnings": st.column_config.NumberColumn(format="localized"),
            "Errors": st.column_config.NumberColumn(format="localized"),
        },
    )
    selected_id = st.selectbox(
        "View run details",
        [record.run_id for record in visible_records],
        format_func=lambda run_id: next(
            f"{record.run_id} · {record.status.value}"
            for record in visible_records
            if record.run_id == run_id
        ),
    )
    selected = next(record for record in visible_records if record.run_id == selected_id)
    with st.expander(f"Run details · {selected.run_id}", expanded=True):
        _render_run_details(
            selected,
            report_available=availability[selected.run_id],
        )


__all__ = ["render_run_history"]
