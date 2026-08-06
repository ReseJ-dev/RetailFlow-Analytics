"""Streamlit settings workspace for supported session overrides."""

from __future__ import annotations

from dataclasses import replace

import streamlit as st

from app.components.header import render_page_header
from app.components.ui import StatusVariant, callout, information_card, status_badge
from app.services.settings_service import (
    SettingsDraft,
    SettingSource,
    SettingsView,
    apply_session_settings,
    draft_from_view,
    load_settings_view,
    mask_database_url,
    reset_session_settings,
)
from app.state import SessionState, StateKey
from retailflow.common.config import StorageSettings
from retailflow.common.exceptions import ConfigurationError

_DUPLICATE_STRATEGIES = (
    "keep_first",
    "keep_latest",
    "exclude_all",
    "error",
    "keep_last",
    "remove_all",
)


def _source_badge(source: SettingSource, *, restart_required: bool = False) -> None:
    suffix = " · restart required" if restart_required else ""
    status_badge(
        f"Source: {source.value}{suffix}",
        StatusVariant.WARNING if restart_required else StatusVariant.NEUTRAL,
    )


def _source(view_sources: object, path: str) -> SettingSource:
    if isinstance(view_sources, dict):
        value = view_sources.get(path, SettingSource.DEFAULT)
        return value if isinstance(value, SettingSource) else SettingSource.DEFAULT
    return SettingSource.DEFAULT


def _render_general(draft: SettingsDraft, sources: object) -> SettingsDraft:
    st.subheader("General")
    st.caption("Defaults used to identify and format newly generated reports.")
    left, middle, right = st.columns(3)
    with left:
        company = st.text_input(
            "Company name",
            value=draft.company_name,
            help="Default organisation name shown in report identity fields.",
        )
        _source_badge(_source(sources, "report.company_name"))
    with middle:
        currency = st.text_input(
            "Default currency",
            value=draft.default_currency,
            max_chars=3,
            help="Three-letter currency code used when source data does not select one.",
        )
        _source_badge(_source(sources, "report.default_currency"))
    with right:
        date_format = st.text_input(
            "Date format",
            value=draft.date_format,
            help="Python-style date format used in generated report presentation.",
        )
        _source_badge(_source(sources, "report.date_format"))
    return replace(
        draft,
        company_name=company,
        default_currency=currency,
        date_format=date_format,
    )


def _render_reporting(draft: SettingsDraft, sources: object) -> SettingsDraft:
    st.subheader("Reporting")
    st.caption("Choose the default optional content and output naming for future reports.")
    options = st.columns(3)
    raw = options[0].checkbox("Processed Data", value=draft.include_raw_data)
    quality = options[1].checkbox("Data Quality", value=draft.include_quality_report)
    inventory = options[2].checkbox("Inventory Analysis", value=draft.include_inventory_analysis)
    returns = options[0].checkbox("Returns Analysis", value=draft.include_returns_analysis)
    recommendations = options[1].checkbox(
        "Management Recommendations", value=draft.include_recommendations
    )
    output, filename = st.columns(2)
    with output:
        output_directory = st.text_input(
            "Output directory",
            value=draft.output_directory,
            help="Local application directory used for newly generated workbooks.",
        )
        _source_badge(_source(sources, "output.output_directory"))
    with filename:
        filename_pattern = st.text_input(
            "Filename pattern",
            value=draft.filename_pattern,
            help="Default workbook pattern; {timestamp} is replaced during generation.",
        )
        _source_badge(_source(sources, "output.filename_pattern"))
    return replace(
        draft,
        include_raw_data=raw,
        include_quality_report=quality,
        include_inventory_analysis=inventory,
        include_returns_analysis=returns,
        include_recommendations=recommendations,
        output_directory=output_directory,
        filename_pattern=filename_pattern,
    )


def _render_validation(draft: SettingsDraft, sources: object) -> SettingsDraft:
    st.subheader("Data Validation")
    st.caption("These choices apply to the next validation run; existing results are unchanged.")
    strategy = st.selectbox(
        "Duplicate strategy",
        _DUPLICATE_STRATEGIES,
        index=_DUPLICATE_STRATEGIES.index(draft.duplicate_strategy),
        help="Controls how duplicate source rows are retained or excluded.",
    )
    _source_badge(_source(sources, "validation.duplicate_strategy"))
    columns = st.columns(3)
    unknown = columns[0].checkbox(
        "Allow unknown products",
        value=draft.allow_unknown_products,
        help="Records referencing products outside the catalogue may continue when supported.",
    )
    exclude = columns[1].checkbox(
        "Exclude invalid rows",
        value=draft.exclude_invalid_rows,
        help="Blocking row-level errors are separated from processed data.",
    )
    strict_warnings = columns[2].checkbox(
        "Allow strict reports with warnings",
        value=draft.allow_report_with_warnings_in_strict_mode,
        help="CLI strict mode may continue with warnings only when explicitly enabled.",
    )
    return replace(
        draft,
        duplicate_strategy=str(strategy),
        allow_unknown_products=unknown,
        exclude_invalid_rows=exclude,
        allow_report_with_warnings_in_strict_mode=strict_warnings,
    )


def _render_inventory(draft: SettingsDraft, sources: object) -> tuple[SettingsDraft, bool]:
    st.subheader("Inventory Thresholds")
    st.caption("Coverage bands must increase strictly: critical < low stock < overstock.")
    columns = st.columns(4)
    critical = columns[0].number_input(
        "Critical coverage days", min_value=0, value=draft.critical_coverage_days
    )
    low = columns[1].number_input(
        "Low-stock coverage days", min_value=0, value=draft.low_coverage_days
    )
    overstock = columns[2].number_input(
        "Overstock coverage days", min_value=0, value=draft.overstock_coverage_days
    )
    dead = columns[3].number_input(
        "Dead-stock days", min_value=0, value=draft.dead_stock_days
    )
    valid = critical < low < overstock
    if valid:
        callout(
            "Threshold order is valid",
            f"Critical ({critical}) < low stock ({low}) < overstock ({overstock}).",
            StatusVariant.SUCCESS,
        )
    else:
        callout(
            "Thresholds cannot be applied",
            "Set critical coverage below low-stock coverage, and low-stock coverage below "
            "overstock coverage.",
            StatusVariant.ERROR,
        )
    _source_badge(_source(sources, "inventory.critical_coverage_days"))
    return (
        replace(
            draft,
            critical_coverage_days=int(critical),
            low_coverage_days=int(low),
            overstock_coverage_days=int(overstock),
            dead_stock_days=int(dead),
        ),
        valid,
    )


def _render_storage(settings: StorageSettings, source: SettingSource) -> None:
    st.subheader("Storage")
    st.caption("Run history uses the configured SQLAlchemy database connection.")
    database_url = str(settings.database_url)
    st.text_input("Database URL", value=mask_database_url(database_url), disabled=True)
    st.checkbox("Create local tables automatically", value=settings.create_tables, disabled=True)
    _source_badge(source, restart_required=True)
    callout(
        "Restart required",
        "Change storage configuration through YAML or environment variables, then restart "
        "the application. Database credentials are never displayed here.",
        StatusVariant.INFORMATION,
    )


def _render_api(draft: SettingsDraft, view: SettingsView) -> SettingsDraft:
    st.subheader("API Connection")
    st.caption("The URL may be overridden for this session; bearer tokens remain environment-only.")
    api_url = st.text_input(
        "API URL",
        value=draft.api_url,
        disabled=True,
        help="Base URL used by the Upload Data API workflow.",
    )
    _source_badge(view.api_url_source)
    token_text = "Configured in environment" if view.api_token_configured else "Not configured"
    st.text_input(
        "Bearer token",
        value="••••••••" if view.api_token_configured else "",
        type="password",
        disabled=True,
        help="Set RETAIL_API_TOKEN outside the application. Its value is never stored in session.",
    )
    status_badge(
        token_text,
        StatusVariant.SUCCESS if view.api_token_configured else StatusVariant.NEUTRAL,
    )
    with st.expander("Connection policy", expanded=False):
        sources = view.settings.sources
        st.write(f"Connect timeout: {sources.api_connect_timeout:g} seconds")
        st.write(f"Read timeout: {sources.api_read_timeout:g} seconds")
        st.write(f"Retry count: {sources.api_retry_count}")
        st.write(f"Page size: {sources.api_page_size}")
        st.caption("Change these runtime options through YAML or environment, then restart.")
    st.caption(
        "Change the active session URL from Upload Data, where connection testing is available."
    )
    return replace(draft, api_url=api_url)


def _render_appearance() -> None:
    st.subheader("Appearance")
    st.caption("Only currently implemented presentation choices are shown.")
    columns = st.columns(3)
    with columns[0]:
        information_card("Light theme", "Accessible fixed light palette.", label="THEME")
    with columns[1]:
        information_card("System fonts", "No remote font dependency.", label="TYPOGRAPHY")
    with columns[2]:
        information_card("Wide workspace", "Responsive content up to 1440 px.", label="LAYOUT")


def render_settings(state: SessionState) -> None:
    """Render understandable settings while applying only supported session overrides."""
    render_page_header(
        page_title="Settings",
        description="Review configuration sources and adjust supported defaults for this session.",
        reporting_period=state[StateKey.SELECTED_REPORTING_PERIOD.value],
        last_successful_run=state[StateKey.LAST_SUCCESSFUL_RUN.value],
        status=state[StateKey.APPLICATION_STATUS.value],
    )
    view = load_settings_view(state)
    draft = draft_from_view(view)
    general_tab, reporting_tab, validation_tab, inventory_tab = st.tabs(
        ["General", "Reporting", "Data Validation", "Inventory Thresholds"]
    )
    with general_tab:
        draft = _render_general(draft, view.sources)
    with reporting_tab:
        draft = _render_reporting(draft, view.sources)
    with validation_tab:
        draft = _render_validation(draft, view.sources)
    with inventory_tab:
        draft, thresholds_valid = _render_inventory(draft, view.sources)

    storage_tab, api_tab, appearance_tab = st.tabs(
        ["Storage", "API Connection", "Appearance"]
    )
    with storage_tab:
        _render_storage(
            view.settings.storage,
            _source(view.sources, "storage.database_url"),
        )
    with api_tab:
        draft = _render_api(draft, view)
    with appearance_tab:
        _render_appearance()

    st.divider()
    callout(
        "Session-only changes",
        "Apply updates only to this browser session. No YAML file is written, and a page "
        "refresh may retain values while restarting the application will not.",
        StatusVariant.INFORMATION,
    )
    apply_column, reset_column = st.columns(2)
    if apply_column.button(
        "Apply to This Session",
        type="primary",
        disabled=not thresholds_valid,
        width="stretch",
    ):
        try:
            apply_session_settings(state, draft)
        except ConfigurationError as error:
            callout("Settings were not applied", error.message, StatusVariant.ERROR)
        else:
            st.success(
                "Settings applied to this session. Existing processed results are unchanged."
            )

    confirm_reset = reset_column.checkbox(
        "Confirm removal of session overrides",
        help=(
            "This does not delete reports, uploaded files, run history, YAML, "
            "or environment values."
        ),
    )
    if reset_column.button(
        "Reset Session Overrides",
        disabled=not confirm_reset,
        width="stretch",
    ):
        try:
            reset_session_settings(state, confirmed=confirm_reset)
        except ConfigurationError as error:
            callout("Reset was not completed", error.message, StatusVariant.ERROR)
        else:
            st.success(
                "Session overrides removed. Configured environment/default values now apply."
            )
            st.rerun()


__all__ = ["render_settings"]
