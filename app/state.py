"""Central, browser-independent application session-state management."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol


class AppPage(StrEnum):
    """Stable labels used by the central application navigation."""

    OVERVIEW = "Overview"
    UPLOAD_DATA = "Upload Data"
    DATA_QUALITY = "Data Quality"
    DASHBOARD = "Dashboard"
    GENERATE_REPORT = "Generate Report"
    RUN_HISTORY = "Run History"
    SETTINGS = "Settings"


class ApplicationStatus(StrEnum):
    """User-facing workflow states displayed in the shared header."""

    READY = "Ready"
    WAITING_FOR_DATA = "Waiting for Data"
    VALIDATING = "Validating"
    PROCESSING = "Processing"
    REPORT_GENERATED = "Report Generated"
    FAILED = "Failed"


class StateKey(StrEnum):
    """Canonical session keys; pages should not invent alternatives."""

    CURRENT_PAGE = "current_page"
    SELECTED_REPORTING_PERIOD = "selected_reporting_period"
    LOADED_DATASETS = "loaded_datasets"
    COLUMN_MAPPINGS = "column_mappings"
    VALIDATION_RESULT = "validation_result"
    PROCESSING_RESULT = "processing_result"
    SALES_ANALYTICS = "sales_analytics"
    INVENTORY_ANALYTICS = "inventory_analytics"
    RETURNS_ANALYTICS = "returns_analytics"
    RECOMMENDATIONS = "recommendations"
    GENERATED_REPORT = "generated_report"
    LAST_SUCCESSFUL_RUN = "last_successful_run"
    APPLICATION_STATUS = "application_status"
    ACTIVE_FILTERS = "active_filters"
    REPORT_SETTINGS = "report_settings"
    CONFIRM_NEW_REPORT = "confirm_new_report"


@dataclass(frozen=True, slots=True)
class LastReportSummary:
    """Small, presentation-only summary of the most recently generated report."""

    reporting_period: str
    orders_processed: int
    products_analysed: int
    warnings: int
    status: ApplicationStatus
    filename: str
    generated_at: datetime
    report_path: Path | None = None
    report_bytes: bytes | None = None


class SessionState(Protocol):
    """Minimal mapping interface shared by dictionaries and Streamlit session state."""

    def __getitem__(self, key: str) -> Any:  # noqa: ANN401
        """Return a stored value."""
        ...

    def __setitem__(self, key: str, value: Any) -> None:  # noqa: ANN401
        """Store a session value."""
        ...

    def __contains__(self, key: object) -> bool:
        """Return whether a key exists."""
        ...

    def clear(self) -> None:
        """Remove every value from the state."""
        ...


type DefaultFactory = Callable[[], Any]


_DEFAULT_FACTORIES: dict[StateKey, DefaultFactory] = {
    StateKey.CURRENT_PAGE: lambda: AppPage.OVERVIEW,
    StateKey.SELECTED_REPORTING_PERIOD: lambda: None,
    StateKey.LOADED_DATASETS: dict,
    StateKey.COLUMN_MAPPINGS: dict,
    StateKey.VALIDATION_RESULT: lambda: None,
    StateKey.PROCESSING_RESULT: lambda: None,
    StateKey.SALES_ANALYTICS: lambda: None,
    StateKey.INVENTORY_ANALYTICS: lambda: None,
    StateKey.RETURNS_ANALYTICS: lambda: None,
    StateKey.RECOMMENDATIONS: list,
    StateKey.GENERATED_REPORT: lambda: None,
    StateKey.LAST_SUCCESSFUL_RUN: lambda: None,
    StateKey.APPLICATION_STATUS: lambda: ApplicationStatus.WAITING_FOR_DATA,
    StateKey.ACTIVE_FILTERS: dict,
    StateKey.REPORT_SETTINGS: dict,
    StateKey.CONFIRM_NEW_REPORT: lambda: False,
}

_TEMPORARY_KEYS = (
    StateKey.SELECTED_REPORTING_PERIOD,
    StateKey.LOADED_DATASETS,
    StateKey.COLUMN_MAPPINGS,
    StateKey.VALIDATION_RESULT,
    StateKey.PROCESSING_RESULT,
    StateKey.SALES_ANALYTICS,
    StateKey.INVENTORY_ANALYTICS,
    StateKey.RETURNS_ANALYTICS,
    StateKey.RECOMMENDATIONS,
    StateKey.ACTIVE_FILTERS,
)


def initialize_state(state: SessionState) -> None:
    """Add every required key without overwriting values from the current session."""
    for key, factory in _DEFAULT_FACTORIES.items():
        if key.value not in state:
            state[key.value] = factory()


def has_unsaved_temporary_state(state: SessionState) -> bool:
    """Return whether a new-report action would discard active working data."""
    initialize_state(state)
    values = (
        state[StateKey.LOADED_DATASETS.value],
        state[StateKey.COLUMN_MAPPINGS.value],
        state[StateKey.VALIDATION_RESULT.value],
        state[StateKey.PROCESSING_RESULT.value],
        state[StateKey.SALES_ANALYTICS.value],
        state[StateKey.INVENTORY_ANALYTICS.value],
        state[StateKey.RETURNS_ANALYTICS.value],
        state[StateKey.RECOMMENDATIONS.value],
    )
    return any(value is not None and value != {} and value != [] for value in values)


def reset_temporary_state(state: SessionState) -> None:
    """Clear in-progress report data while retaining settings and the last report."""
    initialize_state(state)
    for key in _TEMPORARY_KEYS:
        state[key.value] = _DEFAULT_FACTORIES[key]()
    state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.WAITING_FOR_DATA
    state[StateKey.CONFIRM_NEW_REPORT.value] = False


def _value_or_default(state: SessionState, key: StateKey, default: object) -> object:
    try:
        return state[key.value]
    except KeyError:
        return default


def reset_application_state(state: SessionState, *, preserve_last_report: bool = True) -> None:
    """Restore defaults, optionally retaining the last generated report and timestamp."""
    saved_report = _value_or_default(state, StateKey.GENERATED_REPORT, None)
    saved_run = _value_or_default(state, StateKey.LAST_SUCCESSFUL_RUN, None)
    saved_settings = _value_or_default(state, StateKey.REPORT_SETTINGS, {})
    state.clear()
    initialize_state(state)
    if preserve_last_report:
        state[StateKey.GENERATED_REPORT.value] = saved_report
        state[StateKey.LAST_SUCCESSFUL_RUN.value] = saved_run
        state[StateKey.REPORT_SETTINGS.value] = saved_settings


def navigate_to(state: SessionState, page: AppPage) -> None:
    """Set the current page using the central page enum."""
    initialize_state(state)
    state[StateKey.CURRENT_PAGE.value] = page
