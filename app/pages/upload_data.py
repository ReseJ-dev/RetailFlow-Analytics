"""Streamlit file and authenticated REST API source selection."""

from __future__ import annotations

import os

import streamlit as st

from app.components.header import render_page_header
from app.components.layout import navigate_and_rerun
from app.services.api_source_service import (
    load_api_datasets,
    source_summary,
    test_api_connection,
)
from app.state import ApplicationStatus, AppPage, SessionState, StateKey
from retailflow.common.exceptions import RetailFlowError
from retailflow.ingestion import LoadedDataset, load_file


def _clear_downstream_results(state: SessionState) -> None:
    for key in (
        StateKey.VALIDATION_RESULT,
        StateKey.PROCESSING_RESULT,
        StateKey.SALES_ANALYTICS,
        StateKey.INVENTORY_ANALYTICS,
        StateKey.RETURNS_ANALYTICS,
        StateKey.RECOMMENDATIONS,
    ):
        state[key.value] = None if key is not StateKey.RECOMMENDATIONS else []
    state[StateKey.WARNINGS_CONFIRMED.value] = False
    state[StateKey.ISSUE_ACTIONS.value] = {}


def _store_sources(
    state: SessionState,
    datasets: dict[str, LoadedDataset],
    *,
    source_mode: str,
    api_url: str | None = None,
) -> None:
    _clear_downstream_results(state)
    state[StateKey.LOADED_DATASETS.value] = datasets
    state[StateKey.COLUMN_MAPPINGS.value] = {}
    import_settings = state[StateKey.IMPORT_SETTINGS.value]
    settings = dict(import_settings) if isinstance(import_settings, dict) else {}
    settings.update({"source_mode": source_mode})
    if api_url is not None:
        settings["api_url"] = api_url
    settings.pop("api_token", None)
    settings.pop("token", None)
    state[StateKey.IMPORT_SETTINGS.value] = settings
    state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.READY


def _render_file_upload(state: SessionState) -> None:
    st.subheader("Upload files")
    st.caption("Provide all four required datasets. Monthly targets are optional.")
    uploads = {
        "orders": st.file_uploader("Orders", type=("csv", "xlsx"), key="file_orders"),
        "products": st.file_uploader(
            "Products", type=("csv", "xlsx"), key="file_products"
        ),
        "inventory": st.file_uploader(
            "Inventory", type=("csv", "xlsx"), key="file_inventory"
        ),
        "returns": st.file_uploader("Returns", type=("csv", "xlsx"), key="file_returns"),
        "monthly_targets": st.file_uploader(
            "Monthly Targets (optional)",
            type=("csv", "xlsx"),
            key="file_targets",
        ),
    }
    if st.button("Load Uploaded Files", type="primary"):
        missing = [
            name
            for name in ("orders", "products", "inventory", "returns")
            if uploads[name] is None
        ]
        if missing:
            st.error("Upload all required files: " + ", ".join(missing) + ".")
            return
        try:
            datasets = {
                name: load_file(upload.getvalue(), filename=upload.name)
                for name, upload in uploads.items()
                if upload is not None
            }
        except RetailFlowError as error:
            st.error(error.message)
            return
        _store_sources(state, datasets, source_mode="files")
        st.success("Source files loaded successfully.")
        st.dataframe(source_summary(datasets), hide_index=True, width="stretch")


def _render_api_upload(state: SessionState) -> None:
    st.subheader("Load from API")
    st.caption("Credentials are used for this request only and are not stored in run history.")
    api_url = st.text_input(
        "API URL",
        value=os.getenv("RETAIL_API_URL", "http://127.0.0.1:8000"),
    )
    token = st.text_input("Bearer Token", type="password", value="")
    test_column, load_column, _ = st.columns([1, 1, 3])
    if test_column.button("Test Connection"):
        try:
            status = test_api_connection(api_url, token)
        except RetailFlowError as error:
            st.error(error.message)
        else:
            st.success(f"Connection status: {status}")
    if load_column.button("Load Data", type="primary"):
        try:
            with st.spinner("Loading paginated API datasets..."):
                datasets = load_api_datasets(api_url, token)
        except RetailFlowError as error:
            st.error(error.message)
            return
        _store_sources(state, datasets, source_mode="api", api_url=api_url)
        st.success("API datasets loaded successfully.")
        st.dataframe(source_summary(datasets), hide_index=True, width="stretch")
    existing = state[StateKey.LOADED_DATASETS.value]
    settings = state[StateKey.IMPORT_SETTINGS.value]
    if (
        isinstance(existing, dict)
        and existing
        and isinstance(settings, dict)
        and settings.get("source_mode") == "api"
    ):
        st.markdown("#### Loaded API sources")
        st.dataframe(source_summary(existing), hide_index=True, width="stretch")


def render_upload_data(state: SessionState) -> None:
    """Render mutually explicit file and API ingestion workflows."""
    render_page_header(
        page_title="Upload Data",
        description="Load source datasets from files or an authenticated Retail API.",
        reporting_period=state[StateKey.SELECTED_REPORTING_PERIOD.value],
        last_successful_run=state[StateKey.LAST_SUCCESSFUL_RUN.value],
        status=state[StateKey.APPLICATION_STATUS.value],
    )
    file_tab, api_tab = st.tabs(("Upload Files", "Load from API"))
    with file_tab:
        _render_file_upload(state)
    with api_tab:
        _render_api_upload(state)
    loaded = state[StateKey.LOADED_DATASETS.value]
    if (
        isinstance(loaded, dict)
        and loaded
        and st.button("Continue to Data Quality")
    ):
        navigate_and_rerun(state, AppPage.DATA_QUALITY)


__all__ = ["render_upload_data"]
