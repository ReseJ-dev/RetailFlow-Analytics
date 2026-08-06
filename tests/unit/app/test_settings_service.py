"""Tests for safe settings sources and session overrides."""

from __future__ import annotations

from dataclasses import replace

import pytest
from app.services.settings_service import (
    SettingSource,
    apply_session_settings,
    draft_from_view,
    load_settings_view,
    mask_database_url,
    reset_session_settings,
    validate_settings_draft,
)
from app.state import StateKey, initialize_state

from retailflow.common.config import RetailFlowSettings
from retailflow.common.exceptions import ConfigurationError


def _state() -> dict[str, object]:
    state: dict[str, object] = {}
    initialize_state(state)
    return state


def test_environment_and_session_sources_are_identified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    monkeypatch.setenv("RETAILFLOW_REPORT__DEFAULT_CURRENCY", "EUR")
    state[StateKey.REPORT_SETTINGS.value] = {"report": {"company_name": "Session Co"}}

    view = load_settings_view(state)

    assert view.settings.report.company_name == "Session Co"
    assert view.settings.report.default_currency == "EUR"
    assert view.sources["report.company_name"] is SettingSource.SESSION
    assert view.sources["report.default_currency"] is SettingSource.ENVIRONMENT
    assert view.sources["report.date_format"] is SettingSource.DEFAULT


def test_invalid_threshold_order_cannot_be_applied() -> None:
    state = _state()
    draft = replace(
        draft_from_view(load_settings_view(state, base=RetailFlowSettings())),
        critical_coverage_days=30,
        low_coverage_days=20,
    )

    with pytest.raises(ConfigurationError, match="invalid values"):
        validate_settings_draft(draft, base=RetailFlowSettings())
    with pytest.raises(ConfigurationError):
        apply_session_settings(state, draft, base=RetailFlowSettings())
    assert state[StateKey.REPORT_SETTINGS.value] == {}


def test_apply_uses_existing_session_keys_without_storing_tokens() -> None:
    state = _state()
    state[StateKey.REPORT_SETTINGS.value] = {"generation": "preserved"}
    state[StateKey.IMPORT_SETTINGS.value] = {
        "source_mode": "api",
        "api_token": "remove-me",
    }
    draft = replace(
        draft_from_view(load_settings_view(state, base=RetailFlowSettings())),
        company_name="Session Retail",
        default_currency="eur",
        api_url="https://api.example.test",
    )

    applied = apply_session_settings(state, draft, base=RetailFlowSettings())

    report_settings = state[StateKey.REPORT_SETTINGS.value]
    import_settings = state[StateKey.IMPORT_SETTINGS.value]
    assert isinstance(report_settings, dict)
    assert isinstance(import_settings, dict)
    assert report_settings["generation"] == "preserved"
    assert report_settings["report"]["company_name"] == "Session Retail"
    assert import_settings["default_currency"] == "EUR"
    assert import_settings["source_mode"] == "api"
    assert "api_url" not in import_settings
    assert "api_token" not in import_settings
    assert applied.report.default_currency == "EUR"


def test_reset_requires_confirmation_and_preserves_unrelated_state() -> None:
    state = _state()
    state[StateKey.REPORT_SETTINGS.value] = {
        "generation": "preserved",
        "report": {"company_name": "Override"},
    }
    state[StateKey.IMPORT_SETTINGS.value] = {
        "source_mode": "files",
        "default_currency": "EUR",
    }

    with pytest.raises(ConfigurationError, match="Confirm the reset"):
        reset_session_settings(state, confirmed=False)
    reset_session_settings(state, confirmed=True)

    assert state[StateKey.REPORT_SETTINGS.value] == {"generation": "preserved"}
    assert state[StateKey.IMPORT_SETTINGS.value] == {"source_mode": "files"}


def test_database_credentials_are_masked() -> None:
    masked = mask_database_url("postgresql://retail:super-secret@db.example/retailflow")

    assert "super-secret" not in masked
    assert "***" in masked
