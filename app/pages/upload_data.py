"""Streamlit file and authenticated REST API source selection."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

import streamlit as st

from app.components.layout import navigate_and_rerun
from app.components.ui import (
    StatusVariant,
    callout,
    data_source_status,
    information_card,
    page_header,
    section_header,
    status_badge,
)
from app.services.api_source_service import load_api_datasets, test_api_connection
from app.state import ApplicationStatus, AppPage, SessionState, StateKey
from retailflow.common.config import load_config
from retailflow.common.exceptions import RetailFlowError
from retailflow.ingestion import LoadedDataset, load_file

_REQUIRED_DATASETS = ("orders", "products", "inventory", "returns")
_DATASET_LABELS = {
    "orders": "Orders",
    "products": "Products",
    "inventory": "Inventory",
    "returns": "Returns",
    "monthly_targets": "Monthly Targets",
}
_FILE_WIDGET_KEYS = {
    "orders": "file_orders",
    "products": "file_products",
    "inventory": "file_inventory",
    "returns": "file_returns",
    "monthly_targets": "file_targets",
}
_SOURCE_MODE_LABELS = {
    "Files": "files",
    "REST API": "api",
    "Mixed": "mixed",
}


class UploadLike(Protocol):
    """Uploaded-file attributes used without bypassing Streamlit's uploader."""

    name: str
    size: int

    def getvalue(self) -> bytes:
        """Return the uploaded bytes managed by Streamlit."""
        ...


type DatasetLoader = Callable[..., LoadedDataset]


@dataclass(frozen=True, slots=True)
class SourceReadiness:
    """Presentation summary for the currently selected source mode."""

    ready_count: int
    required_count: int
    missing_required: tuple[str, ...]

    @property
    def ready(self) -> bool:
        """Return whether all required sources are selected or loaded."""
        return not self.missing_required


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
    state[StateKey.APPLICATION_STATUS.value] = (
        ApplicationStatus.READY
        if all(name in datasets for name in _REQUIRED_DATASETS)
        else ApplicationStatus.WAITING_FOR_DATA
    )


def _active_datasets(state: SessionState, mode: str) -> dict[str, LoadedDataset]:
    raw = state[StateKey.LOADED_DATASETS.value]
    settings = state[StateKey.IMPORT_SETTINGS.value]
    stored_mode = settings.get("source_mode") if isinstance(settings, Mapping) else None
    if not isinstance(raw, Mapping):
        return {}
    if mode != "mixed" and stored_mode not in {mode, "mixed"}:
        return {}
    return {
        str(name): dataset for name, dataset in raw.items() if isinstance(dataset, LoadedDataset)
    }


def _format_file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _same_upload(
    upload: UploadLike,
    dataset: LoadedDataset | None,
    *,
    loaded_file_id: str | None = None,
) -> bool:
    metadata_matches = bool(
        dataset is not None and upload.name == dataset.filename and upload.size == dataset.file_size
    )
    upload_file_id = getattr(upload, "file_id", None)
    return metadata_matches and (loaded_file_id is None or upload_file_id == loaded_file_id)


def _file_widget_key(dataset_name: str) -> str:
    base_key = _FILE_WIDGET_KEYS[dataset_name]
    version = int(st.session_state.get(f"_{base_key}_version", 0))
    return base_key if version == 0 else f"{base_key}_{version}"


def _error_key(dataset_name: str) -> str:
    return f"_source_error_{dataset_name}"


def _file_id_key(dataset_name: str) -> str:
    return f"_source_file_id_{dataset_name}"


def _read_uploaded_source(
    dataset_name: str,
    upload: UploadLike,
    *,
    loader: DatasetLoader = load_file,
) -> LoadedDataset | None:
    try:
        dataset = loader(upload.getvalue(), filename=upload.name)
    except RetailFlowError as error:
        st.session_state[_error_key(dataset_name)] = error.message
        return None
    st.session_state.pop(_error_key(dataset_name), None)
    upload_file_id = getattr(upload, "file_id", None)
    if upload_file_id is not None:
        st.session_state[_file_id_key(dataset_name)] = str(upload_file_id)
    return dataset


def _save_file_source(
    state: SessionState,
    dataset_name: str,
    upload: UploadLike,
    *,
    mode: str,
) -> bool:
    dataset = _read_uploaded_source(dataset_name, upload)
    if dataset is None:
        return False
    datasets = _active_datasets(state, mode)
    datasets[dataset_name] = dataset
    api_url = None
    settings = state[StateKey.IMPORT_SETTINGS.value]
    if isinstance(settings, Mapping):
        api_value = settings.get("api_url")
        api_url = str(api_value) if api_value else None
    _store_sources(state, datasets, source_mode=mode, api_url=api_url)
    return True


def _remove_file_source(state: SessionState, dataset_name: str, *, mode: str) -> None:
    datasets = _active_datasets(state, mode)
    datasets.pop(dataset_name, None)
    _store_sources(state, datasets, source_mode=mode)
    st.session_state.pop(_error_key(dataset_name), None)
    st.session_state.pop(_file_id_key(dataset_name), None)
    base_key = _FILE_WIDGET_KEYS[dataset_name]
    version_key = f"_{base_key}_version"
    st.session_state[version_key] = int(st.session_state.get(version_key, 0)) + 1
    st.rerun()


def _render_dataset_card(
    state: SessionState,
    dataset_name: str,
    *,
    required: bool,
    mode: str,
) -> UploadLike | None:
    datasets = _active_datasets(state, mode)
    loaded = datasets.get(dataset_name)
    label = _DATASET_LABELS[dataset_name]
    with st.container(border=True):
        title_column, badge_column = st.columns([3, 2])
        title_column.markdown(f"**{label}**")
        with badge_column:
            status_badge(
                "Required" if required else "Optional",
                StatusVariant.INFORMATION if required else StatusVariant.NEUTRAL,
                accessible_label=f"{label}: {'required' if required else 'optional'} dataset",
            )
        st.caption("Supported formats: CSV, XLSX")
        upload_value = st.file_uploader(
            f"Select {label}",
            type=("csv", "xlsx"),
            key=_file_widget_key(dataset_name),
            help=f"Choose a CSV or XLSX file containing {label.lower()} data.",
        )
        upload: UploadLike | None = upload_value
        if upload is not None:
            st.caption(f"Selected: {upload.name} · {_format_file_size(upload.size)}")
        loaded_file_id_value = st.session_state.get(_file_id_key(dataset_name))
        loaded_file_id = str(loaded_file_id_value) if loaded_file_id_value else None
        changed = upload is not None and not _same_upload(
            upload,
            loaded,
            loaded_file_id=loaded_file_id,
        )
        if loaded is not None:
            status_text = "Replacement selected" if changed else "Loaded and ready"
            status_badge(
                status_text,
                StatusVariant.WARNING if changed else StatusVariant.SUCCESS,
                accessible_label=f"{label} upload status: {status_text}",
            )
            details = [
                f"File: {loaded.filename}",
                f"Size: {_format_file_size(loaded.file_size)}",
                f"Rows: {loaded.row_count:,}",
            ]
            if loaded.selected_sheet_name:
                details.append(f"Sheet: {loaded.selected_sheet_name}")
            st.caption(" · ".join(details))
        elif upload is not None:
            status_badge(
                "Selected; ready to read",
                StatusVariant.INFORMATION,
                accessible_label=f"{label} upload status: selected and ready to read",
            )
        else:
            status_badge(
                "Required source missing" if required else "Not provided",
                StatusVariant.WARNING if required else StatusVariant.NEUTRAL,
                accessible_label=f"{label} upload status: not provided",
            )

        error = st.session_state.get(_error_key(dataset_name))
        if error:
            callout(
                "File could not be read",
                str(error),
                StatusVariant.ERROR,
                accessible_label=f"{label} parsing error",
            )
        replace_column, remove_column = st.columns(2)
        read_label = "Replace" if loaded is not None else "Read File"
        if replace_column.button(
            read_label,
            key=f"read_{dataset_name}",
            disabled=upload is None or not changed,
            width="stretch",
        ):
            assert upload is not None
            if _save_file_source(state, dataset_name, upload, mode=mode):
                st.rerun()
            st.error(f"{label}: {st.session_state[_error_key(dataset_name)]}")
        if remove_column.button(
            "Remove",
            key=f"remove_{dataset_name}",
            disabled=upload is None and loaded is None,
            width="stretch",
        ):
            _remove_file_source(state, dataset_name, mode=mode)
        return upload


def _render_file_sources(state: SessionState, *, mode: str) -> dict[str, UploadLike | None]:
    section_header(
        "Required datasets",
        "All four datasets are required before validation can begin.",
    )
    uploads: dict[str, UploadLike | None] = {}
    for start in range(0, len(_REQUIRED_DATASETS), 2):
        dataset_pair = _REQUIRED_DATASETS[start : start + 2]
        for column, dataset_name in zip(st.columns(2), dataset_pair, strict=True):
            with column:
                uploads[dataset_name] = _render_dataset_card(
                    state,
                    dataset_name,
                    required=True,
                    mode=mode,
                )
    section_header(
        "Optional datasets",
        "Monthly targets add target comparisons but are not required for validation.",
    )
    uploads["monthly_targets"] = _render_dataset_card(
        state,
        "monthly_targets",
        required=False,
        mode=mode,
    )
    return uploads


def _api_url_default(state: SessionState) -> str:
    import_settings = state[StateKey.IMPORT_SETTINGS.value]
    stored = import_settings.get("api_url") if isinstance(import_settings, Mapping) else None
    configured = load_config().sources.api_url
    return str(stored or os.getenv("RETAIL_API_URL") or configured or "http://127.0.0.1:8000")


def _render_api_endpoint_statuses(state: SessionState, *, mode: str) -> None:
    section_header("API endpoints", "Required resources loaded from the configured Retail API.")
    datasets = _active_datasets(state, mode)
    for column, dataset_name in zip(st.columns(4), _REQUIRED_DATASETS, strict=True):
        dataset = datasets.get(dataset_name)
        with column:
            data_source_status(
                _DATASET_LABELS[dataset_name],
                "Loaded" if dataset is not None else "Not loaded",
                variant=StatusVariant.SUCCESS if dataset is not None else StatusVariant.NEUTRAL,
                detail=f"Endpoint: /api/{dataset_name}",
                row_count=dataset.row_count if dataset is not None else None,
            )


def _render_api_sources(state: SessionState, *, mode: str) -> None:
    section_header(
        "REST API connection",
        "Credentials are used for requests only and are never stored in run history.",
    )
    api_url = st.text_input("API URL", value=_api_url_default(state), key="retail_api_url")
    token = st.text_input(
        "Bearer Token",
        type="password",
        value="",
        key="retail_api_token",
        help="The token remains masked and is not written to application logs or SQLite.",
    )
    connection_error = st.session_state.get("_api_connection_error")
    connection_status = st.session_state.get("_api_connection_status")
    test_label = "Retry Connection" if connection_error else "Test Connection"
    test_column, load_column, _ = st.columns([1, 1, 3])
    if test_column.button(test_label, key="test_api_connection", width="stretch"):
        try:
            with st.spinner("Testing API connection..."):
                status = test_api_connection(api_url, token)
        except RetailFlowError as error:
            st.session_state["_api_connection_error"] = error.message
            st.session_state.pop("_api_connection_status", None)
            connection_error = error.message
            connection_status = None
        else:
            st.session_state["_api_connection_status"] = status
            st.session_state.pop("_api_connection_error", None)
            connection_status = status
            connection_error = None
    load_error = st.session_state.get("_api_load_error")
    load_label = "Retry Load" if load_error else "Load Data"
    if load_column.button(load_label, key="load_api_data", type="primary", width="stretch"):
        try:
            with st.spinner("Loading paginated API datasets..."):
                api_datasets = load_api_datasets(api_url, token)
        except RetailFlowError as error:
            st.session_state["_api_load_error"] = error.message
            load_error = error.message
        else:
            datasets = api_datasets
            if mode == "mixed":
                file_datasets = {
                    name: dataset
                    for name, dataset in _active_datasets(state, mode).items()
                    if dataset.file_type != "api"
                }
                datasets.update(file_datasets)
            _store_sources(state, datasets, source_mode=mode, api_url=api_url)
            st.session_state.pop("_api_load_error", None)
            load_error = None
            st.success("API datasets loaded successfully.")
    if connection_error:
        callout(
            "Connection failed",
            str(connection_error),
            StatusVariant.ERROR,
            accessible_label="REST API connection error",
        )
    elif connection_status:
        callout(
            "Connection available",
            f"Health status: {connection_status}",
            StatusVariant.SUCCESS,
        )
    if load_error:
        callout(
            "API data could not be loaded",
            str(load_error),
            StatusVariant.ERROR,
            accessible_label="REST API loading error",
        )
    _render_api_endpoint_statuses(state, mode=mode)


def _readiness(
    datasets: Mapping[str, LoadedDataset],
    uploads: Mapping[str, UploadLike | None],
) -> SourceReadiness:
    missing = tuple(
        _DATASET_LABELS[name]
        for name in _REQUIRED_DATASETS
        if name not in datasets and uploads.get(name) is None
    )
    return SourceReadiness(
        ready_count=len(_REQUIRED_DATASETS) - len(missing),
        required_count=len(_REQUIRED_DATASETS),
        missing_required=missing,
    )


def _load_changed_files(
    state: SessionState,
    uploads: Mapping[str, UploadLike | None],
    *,
    mode: str,
) -> dict[str, LoadedDataset] | None:
    datasets = _active_datasets(state, mode)
    for dataset_name, upload in uploads.items():
        existing = datasets.get(dataset_name)
        loaded_file_id_value = st.session_state.get(_file_id_key(dataset_name))
        loaded_file_id = str(loaded_file_id_value) if loaded_file_id_value else None
        if upload is None or _same_upload(
            upload,
            existing,
            loaded_file_id=loaded_file_id,
        ):
            continue
        loaded = _read_uploaded_source(dataset_name, upload)
        if loaded is None:
            _store_sources(state, datasets, source_mode=mode)
            label = _DATASET_LABELS[dataset_name]
            error = st.session_state.get(_error_key(dataset_name), "The file could not be read.")
            st.error(f"{label}: {error}")
            return None
        datasets[dataset_name] = loaded
    return datasets


def _render_readiness_summary(
    readiness: SourceReadiness,
    *,
    mode: str,
) -> None:
    section_header("Readiness summary", "Confirm source coverage before validation.")
    if readiness.ready:
        callout(
            "Ready to validate",
            f"All {readiness.required_count} required datasets are available in {mode} mode.",
            StatusVariant.SUCCESS,
        )
        return
    missing = ", ".join(readiness.missing_required)
    callout(
        f"{readiness.ready_count} of {readiness.required_count} required datasets ready",
        f"Still required: {missing}. Add these sources to enable validation.",
        StatusVariant.WARNING,
    )


def _reset_sources(state: SessionState) -> None:
    """Clear source inputs and derived state without retaining API credentials."""
    _clear_downstream_results(state)
    state[StateKey.LOADED_DATASETS.value] = {}
    state[StateKey.COLUMN_MAPPINGS.value] = {}
    state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.WAITING_FOR_DATA
    import_settings = state[StateKey.IMPORT_SETTINGS.value]
    settings = dict(import_settings) if isinstance(import_settings, Mapping) else {}
    settings.pop("source_mode", None)
    settings.pop("api_url", None)
    settings.pop("api_token", None)
    settings.pop("token", None)
    state[StateKey.IMPORT_SETTINGS.value] = settings
    for dataset_name, base_key in _FILE_WIDGET_KEYS.items():
        version_key = f"_{base_key}_version"
        current_key = _file_widget_key(dataset_name)
        st.session_state.pop(current_key, None)
        st.session_state.pop(_file_id_key(dataset_name), None)
        st.session_state[version_key] = int(st.session_state.get(version_key, 0)) + 1
    for key in (
        "retail_api_url",
        "retail_api_token",
        "_api_connection_error",
        "_api_connection_status",
        "_api_load_error",
    ):
        st.session_state.pop(key, None)


def _selected_mode(state: SessionState) -> str:
    settings = load_config()
    options = ["Files", "REST API"]
    if settings.sources.allow_mixed_sources:
        options.append("Mixed")
    import_settings = state[StateKey.IMPORT_SETTINGS.value]
    stored_mode = (
        import_settings.get("source_mode") if isinstance(import_settings, Mapping) else None
    )
    default_label = next(
        (label for label, mode in _SOURCE_MODE_LABELS.items() if mode == stored_mode),
        "REST API" if settings.sources.mode == "api" else "Files",
    )
    if default_label not in options:
        default_label = "Files"
    selected = st.segmented_control(
        "Source mode",
        options,
        default=default_label,
        key="upload_source_mode",
        help="File and API sources are combined only when mixed mode is explicitly enabled.",
    )
    return _SOURCE_MODE_LABELS[str(selected or default_label)]


def render_upload_data(state: SessionState) -> None:
    """Render explicit, rerun-safe file and API ingestion workflows."""
    page_header(
        "Upload Data",
        "Load required retail datasets from files or an authenticated REST API.",
    )
    mode = _selected_mode(state)
    uploads: dict[str, UploadLike | None] = {}
    if mode in {"files", "mixed"}:
        uploads = _render_file_sources(state, mode=mode)
    if mode in {"api", "mixed"}:
        if mode == "mixed":
            st.divider()
        _render_api_sources(state, mode=mode)

    datasets = _active_datasets(state, mode)
    readiness = _readiness(datasets, uploads)
    st.divider()
    _render_readiness_summary(readiness, mode=mode)
    information_card(
        "Column mapping is preserved",
        "RetailFlow applies the existing automatic and manual column-mapping flow during "
        "validation.",
        label="NEXT STEP",
    )
    validate_column, reset_column, _ = st.columns([1, 1, 3])
    if validate_column.button(
        "Validate Data",
        key="validate_uploaded_data",
        type="primary",
        disabled=not readiness.ready,
        help=(
            None
            if readiness.ready
            else "Missing required sources: " + ", ".join(readiness.missing_required)
        ),
        width="stretch",
    ):
        resolved = datasets
        if mode in {"files", "mixed"}:
            loaded = _load_changed_files(state, uploads, mode=mode)
            if loaded is None:
                return
            resolved = loaded
        _store_sources(
            state,
            resolved,
            source_mode=mode,
            api_url=(
                str(st.session_state.get("retail_api_url"))
                if mode in {"api", "mixed"} and st.session_state.get("retail_api_url")
                else None
            ),
        )
        navigate_and_rerun(state, AppPage.DATA_QUALITY)
    reset_column.button(
        "Reset Sources",
        key="reset_sources",
        disabled=not datasets and not any(uploads.values()),
        on_click=_reset_sources,
        args=(state,),
        width="stretch",
    )


__all__ = ["render_upload_data"]
