from app.components.layout import (
    NAVIGATION_ITEMS,
    PRIMARY_NAVIGATION_ITEMS,
    SECONDARY_NAVIGATION_ITEMS,
    NavigationItem,
    render_navigation_item,
)
from app.state import AppPage, StateKey, initialize_state
from streamlit.testing.v1 import AppTest


def test_navigation_registry_contains_every_page_once() -> None:
    pages = tuple(item.page for item in NAVIGATION_ITEMS)

    assert pages == tuple(AppPage)
    assert len(set(pages)) == len(pages)
    assert tuple(item.page for item in PRIMARY_NAVIGATION_ITEMS) == (
        AppPage.OVERVIEW,
        AppPage.UPLOAD_DATA,
        AppPage.DATA_QUALITY,
        AppPage.DASHBOARD,
        AppPage.GENERATE_REPORT,
        AppPage.RUN_HISTORY,
    )
    assert tuple(item.page for item in SECONDARY_NAVIGATION_ITEMS) == (AppPage.SETTINGS,)


def test_navigation_item_uses_button_state_without_mutating_workflow_data(
    monkeypatch,
) -> None:
    state: dict[str, object] = {}
    initialize_state(state)
    loaded_data = {"orders": object()}
    state[StateKey.LOADED_DATASETS.value] = loaded_data
    captured: dict[str, object] = {}

    def capture_button(label: str, **kwargs) -> bool:
        captured.update({"label": label, **kwargs})
        callback = kwargs["on_click"]
        callback(*kwargs["args"])
        return True

    monkeypatch.setattr("app.components.layout.st.button", capture_button)
    item = next(item for item in NAVIGATION_ITEMS if item.page is AppPage.DASHBOARD)

    render_navigation_item(state, item, current_page=AppPage.OVERVIEW)

    assert captured["label"] == "Dashboard"
    assert captured["icon"] == ":material/space_dashboard:"
    assert captured["type"] == "tertiary"
    assert captured["width"] == "stretch"
    assert state[StateKey.CURRENT_PAGE.value] is AppPage.DASHBOARD
    assert state[StateKey.LOADED_DATASETS.value] is loaded_data


def test_active_navigation_item_uses_the_active_button_variant(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def capture_button(label: str, **kwargs) -> bool:
        captured.update({"label": label, **kwargs})
        return False

    monkeypatch.setattr("app.components.layout.st.button", capture_button)
    state: dict[str, object] = {}
    initialize_state(state)
    item = NavigationItem(AppPage.OVERVIEW, ":material/home:", "Overview", True)

    render_navigation_item(state, item, current_page=AppPage.OVERVIEW)

    assert captured["type"] == "primary"
    assert captured["key"] == "navigation_overview"


def test_app_shell_has_one_button_navigation_and_preserves_state_on_rerun() -> None:
    app = AppTest.from_file("app/main.py", default_timeout=10).run()

    assert not app.exception
    assert len(app.sidebar.radio) == 0
    assert [button.label for button in app.sidebar.button] == [
        "Overview",
        "Upload Data",
        "Data Quality",
        "Dashboard",
        "Generate Report",
        "Run History",
        "Settings",
    ]
    app.session_state[StateKey.REPORT_SETTINGS.value] = {"company_name": "Northstar"}

    upload_button = next(
        button for button in app.sidebar.button if button.label == AppPage.UPLOAD_DATA.value
    )
    app = upload_button.click().run()

    assert not app.exception
    assert app.title[0].value == AppPage.UPLOAD_DATA.value
    assert app.session_state[StateKey.CURRENT_PAGE.value] is AppPage.UPLOAD_DATA
    assert app.session_state[StateKey.REPORT_SETTINGS.value] == {
        "company_name": "Northstar"
    }

    refreshed = app.run()
    assert not refreshed.exception
    assert refreshed.title[0].value == AppPage.UPLOAD_DATA.value
    assert refreshed.session_state[StateKey.CURRENT_PAGE.value] is AppPage.UPLOAD_DATA
