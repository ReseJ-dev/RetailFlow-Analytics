"""Tests for browser-independent session-state transitions."""

from datetime import UTC, datetime

from app.state import (
    ApplicationStatus,
    AppPage,
    StateKey,
    has_unsaved_temporary_state,
    initialize_state,
    navigate_to,
    reset_application_state,
    reset_temporary_state,
)


def test_initialize_state_adds_every_required_key_without_overwriting() -> None:
    state: dict[str, object] = {StateKey.CURRENT_PAGE.value: AppPage.SETTINGS}

    initialize_state(state)

    assert set(key.value for key in StateKey) <= state.keys()
    assert state[StateKey.CURRENT_PAGE.value] is AppPage.SETTINGS
    assert state[StateKey.LOADED_DATASETS.value] == {}
    assert state[StateKey.APPLICATION_STATUS.value] is ApplicationStatus.WAITING_FOR_DATA


def test_mutable_defaults_are_not_shared_between_sessions() -> None:
    first: dict[str, object] = {}
    second: dict[str, object] = {}
    initialize_state(first)
    initialize_state(second)

    loaded = first[StateKey.LOADED_DATASETS.value]
    assert isinstance(loaded, dict)
    loaded["orders"] = object()

    assert second[StateKey.LOADED_DATASETS.value] == {}


def test_temporary_reset_clears_working_data_but_preserves_last_report() -> None:
    last_report = object()
    last_run = datetime(2025, 1, 31, tzinfo=UTC)
    state: dict[str, object] = {}
    initialize_state(state)
    state[StateKey.LOADED_DATASETS.value] = {"orders": object()}
    state[StateKey.PROCESSING_RESULT.value] = object()
    state[StateKey.GENERATED_REPORT.value] = last_report
    state[StateKey.LAST_SUCCESSFUL_RUN.value] = last_run
    state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.PROCESSING

    assert has_unsaved_temporary_state(state)
    reset_temporary_state(state)

    assert not has_unsaved_temporary_state(state)
    assert state[StateKey.GENERATED_REPORT.value] is last_report
    assert state[StateKey.LAST_SUCCESSFUL_RUN.value] == last_run
    assert state[StateKey.APPLICATION_STATUS.value] is ApplicationStatus.WAITING_FOR_DATA


def test_full_reset_can_remove_report_and_returns_to_overview() -> None:
    state: dict[str, object] = {}
    initialize_state(state)
    navigate_to(state, AppPage.DASHBOARD)
    state[StateKey.GENERATED_REPORT.value] = object()

    reset_application_state(state, preserve_last_report=False)

    assert state[StateKey.CURRENT_PAGE.value] is AppPage.OVERVIEW
    assert state[StateKey.GENERATED_REPORT.value] is None


def test_full_reset_preserves_report_settings_when_requested() -> None:
    state: dict[str, object] = {}
    initialize_state(state)
    settings = {"company_name": "Northstar Retail"}
    state[StateKey.REPORT_SETTINGS.value] = settings
    state[StateKey.GENERATED_REPORT.value] = "report"

    reset_application_state(state)

    assert state[StateKey.REPORT_SETTINGS.value] == settings
    assert state[StateKey.GENERATED_REPORT.value] == "report"
