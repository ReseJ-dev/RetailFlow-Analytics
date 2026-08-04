"""Streamlit Generate Report workflow."""

from __future__ import annotations

import logging
from collections.abc import Mapping

import streamlit as st

from app.components.empty_state import render_empty_state
from app.components.header import render_page_header
from app.components.layout import navigate_and_rerun
from app.components.report_progress import create_report_progress
from app.components.report_result import render_report_result
from app.components.report_settings import render_report_settings
from app.services.report_service import (
    ReportRequest,
    ReportServiceResult,
    check_report_prerequisites,
    default_report_request,
    generate_management_report,
)
from app.state import AppPage, SessionState, StateKey
from retailflow.common.config import RetailFlowSettings, load_config
from retailflow.common.exceptions import RetailFlowError
from retailflow.models import ProcessingResult

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


def render_generate_report(state: SessionState) -> None:
    """Render report preconditions, settings, progress, result, and downloads."""
    render_page_header(
        page_title="Generate Report",
        description="Configure and create a polished Excel management workbook.",
        reporting_period=state[StateKey.SELECTED_REPORTING_PERIOD.value],
        last_successful_run=state[StateKey.LAST_SUCCESSFUL_RUN.value],
        status=state[StateKey.APPLICATION_STATUS.value],
    )
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
        st.divider()
        st.caption("Adjust the settings below to generate another workbook.")

    processing = state[StateKey.PROCESSING_RESULT.value]
    assert isinstance(processing, ProcessingResult)
    settings = _application_settings(state)
    defaults = _form_defaults(state, settings, processing)
    request = render_report_settings(
        defaults,
        currency_options=_currency_options(processing),
    )
    if request is None:
        return

    callback = create_report_progress()
    try:
        result = generate_management_report(state, request, progress_callback=callback)
    except RetailFlowError as error:
        st.error(error.message)
        return
    render_report_result(state, result)


__all__ = ["render_generate_report"]
