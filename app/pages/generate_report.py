"""Streamlit Generate Report workflow."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

import streamlit as st

from app.components.empty_state import render_empty_state
from app.components.layout import navigate_and_rerun
from app.components.report_progress import create_report_progress
from app.components.report_result import render_report_result
from app.components.report_settings import ReportInputSummary, render_report_settings
from app.components.ui import StatusVariant, callout, page_header
from app.services.report_service import (
    ReportRequest,
    ReportServiceResult,
    check_report_prerequisites,
    default_report_request,
    generate_management_report,
)
from app.state import ApplicationStatus, AppPage, SessionState, StateKey
from retailflow.common.config import RetailFlowSettings, load_config
from retailflow.common.exceptions import RetailFlowError
from retailflow.models import ProcessingResult
from retailflow.validation import ValidationSeverity

logger = logging.getLogger("retailflow.app.generate_report")


def _application_settings(state: SessionState) -> RetailFlowSettings:
    raw = state[StateKey.REPORT_SETTINGS.value]
    if isinstance(raw, Mapping):
        config_values = {
            key: value
            for key, value in raw.items()
            if key in {"report", "inventory", "validation", "output"}
        }
        if config_values:
            try:
                return RetailFlowSettings.model_validate(config_values)
            except ValueError:
                logger.warning("Session report settings were invalid; using application defaults")
    return load_config()


def _form_defaults(
    state: SessionState, settings: RetailFlowSettings, processing: ProcessingResult
) -> ReportRequest:
    raw = state[StateKey.REPORT_SETTINGS.value]
    previous = raw.get("generation") if isinstance(raw, Mapping) else None
    if isinstance(previous, ReportRequest):
        return previous
    return default_report_request(settings, processing)


def _currency_options(processing: ProcessingResult) -> tuple[str, ...]:
    if "currency" not in processing.processed_orders:
        return ()
    values = processing.processed_orders["currency"].dropna().astype(str).str.upper()
    return tuple(sorted(value for value in values.unique() if value))


def _required_page(value: str | None) -> AppPage:
    if value == AppPage.DATA_QUALITY.value:
        return AppPage.DATA_QUALITY
    if value == AppPage.DASHBOARD.value:
        return AppPage.DASHBOARD
    return AppPage.UPLOAD_DATA


def _source_summary(processing: ProcessingResult) -> ReportInputSummary:
    return ReportInputSummary(
        processed_rows=len(processing.processed_orders),
        product_rows=len(processing.products),
        inventory_rows=len(processing.inventory),
        return_rows=len(processing.returns),
        excluded_rows=processing.statistics.total_excluded_rows,
        warning_count=sum(
            issue.severity is ValidationSeverity.WARNING
            for issue in processing.validation_issues
        ),
    )


def _safe_diagnostic_detail(error: RetailFlowError) -> str | None:
    """Return non-sensitive diagnostics while suppressing paths and credentials."""
    detail = error.technical_detail
    if not detail:
        return None
    lowered = detail.casefold()
    sensitive_markers = ("token", "secret", "password", "authorization", "bearer")
    if any(marker in lowered for marker in sensitive_markers):
        return None
    if "/" in detail or "\\" in detail or str(Path.home()) in detail:
        return None
    return detail[:1000]


def _render_generation_error(error: RetailFlowError) -> None:
    callout("Report was not generated", error.message, StatusVariant.ERROR)
    detail = _safe_diagnostic_detail(error)
    if detail:
        with st.expander("Technical diagnostics"):
            st.code(detail, language=None)


def _render_header(state: SessionState) -> None:
    context: list[str] = []
    period = state[StateKey.SELECTED_REPORTING_PERIOD.value]
    if period:
        context.append(f"Reporting period: {period}")
    generated_at = state[StateKey.LAST_SUCCESSFUL_RUN.value]
    if isinstance(generated_at, datetime):
        context.append(f"Last generated: {generated_at.astimezone():%d %b %Y, %H:%M}")
    page_header(
        "Generate Report",
        "Configure and create a polished Excel management workbook.",
        context=context,
    )


def render_generate_report(state: SessionState) -> None:
    """Render report preconditions, settings, progress, result, and downloads."""
    _render_header(state)
    prerequisite = check_report_prerequisites(state)
    if not prerequisite.ready:
        render_empty_state("Complete the preceding step", prerequisite.message)
        destination = _required_page(prerequisite.required_page)
        if st.button(f"Go to {destination.value}", type="primary"):
            navigate_and_rerun(state, destination)
        return

    existing = state[StateKey.GENERATED_REPORT.value]
    if isinstance(existing, ReportServiceResult):
        render_report_result(state, existing)
        if st.button("Generate Another Report"):
            state[StateKey.GENERATED_REPORT.value] = None
            st.rerun()
        return

    processing = state[StateKey.PROCESSING_RESULT.value]
    assert isinstance(processing, ProcessingResult)
    settings = _application_settings(state)
    defaults = _form_defaults(state, settings, processing)
    request = render_report_settings(
        defaults,
        currency_options=_currency_options(processing),
        source_summary=_source_summary(processing),
        generation_in_progress=(
            state[StateKey.APPLICATION_STATUS.value] == ApplicationStatus.PROCESSING
        ),
    )
    if request is None:
        return

    callback = create_report_progress()
    try:
        with st.spinner("Generating Excel report..."):
            generate_management_report(state, request, progress_callback=callback)
    except RetailFlowError as error:
        _render_generation_error(error)
        return
    st.rerun()


__all__ = ["render_generate_report"]
