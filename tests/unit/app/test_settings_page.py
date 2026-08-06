"""Streamlit behavior tests for the Settings workspace."""

from __future__ import annotations

from app.state import AppPage, StateKey
from streamlit.testing.v1 import AppTest


def _open_settings() -> AppTest:
    app = AppTest.from_file("app/main.py", default_timeout=10).run()
    app.session_state[StateKey.CURRENT_PAGE.value] = AppPage.SETTINGS
    return app.run()


def test_settings_page_renders_supported_groups_and_masks_token(monkeypatch) -> None:
    monkeypatch.setenv("RETAIL_API_TOKEN", "never-render-this-token")

    app = _open_settings()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "General",
        "Reporting",
        "Data Validation",
        "Inventory Thresholds",
        "Storage",
        "API Connection",
        "Appearance",
    ]
    token = next(item for item in app.text_input if item.label == "Bearer token")
    assert token.value == "••••••••"
    assert "never-render-this-token" not in str(app)
    assert next(
        button for button in app.button if button.label == "Reset Session Overrides"
    ).disabled


def test_invalid_inventory_thresholds_disable_apply_action() -> None:
    app = _open_settings()
    critical = next(
        item for item in app.number_input if item.label == "Critical coverage days"
    )

    app = critical.set_value(30).run()

    apply_button = next(
        button for button in app.button if button.label == "Apply to This Session"
    )
    assert apply_button.disabled
    assert any("Thresholds cannot be applied" in item.value for item in app.markdown)


def test_apply_stores_only_session_overrides() -> None:
    app = _open_settings()
    company = next(item for item in app.text_input if item.label == "Company name")
    app = company.set_value("Session Retail").run()
    apply_button = next(
        button for button in app.button if button.label == "Apply to This Session"
    )

    app = apply_button.click().run()

    assert not app.exception
    stored = app.session_state[StateKey.REPORT_SETTINGS.value]
    assert stored["report"]["company_name"] == "Session Retail"
    assert "token" not in str(stored).casefold()
