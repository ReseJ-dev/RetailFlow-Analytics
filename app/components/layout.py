"""Central navigation, CSS loading, and placeholder layout."""

from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from app.components.empty_state import render_empty_state
from app.components.header import render_page_header
from app.state import AppPage, SessionState, StateKey, navigate_to

NAVIGATION_WIDGET_KEY = "_retailflow_navigation"


@dataclass(frozen=True, slots=True)
class NavigationItem:
    """One centrally-defined application destination."""

    page: AppPage
    icon: str
    description: str
    implemented: bool = False


NAVIGATION_ITEMS = (
    NavigationItem(AppPage.OVERVIEW, "⌂", "Start a report and review recent activity.", True),
    NavigationItem(AppPage.UPLOAD_DATA, "↑", "Upload and map source datasets."),
    NavigationItem(AppPage.DATA_QUALITY, "✓", "Review validation results and exclusions."),
    NavigationItem(AppPage.DASHBOARD, "▦", "Explore sales, returns, and inventory analytics."),
    NavigationItem(AppPage.GENERATE_REPORT, "↓", "Configure and create an Excel report."),
    NavigationItem(AppPage.RUN_HISTORY, "◷", "Review previous processing runs."),
    NavigationItem(AppPage.SETTINGS, "⚙", "Manage report and validation preferences."),
)


def load_local_css(css_path: Path) -> None:
    """Load trusted application CSS from disk and fail gracefully if unavailable."""
    try:
        css = css_path.read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_navigation(state: SessionState) -> AppPage:
    """Render the single navigation registry and synchronize the selected page."""
    labels = [item.page.value for item in NAVIGATION_ITEMS]
    current = AppPage(state[StateKey.CURRENT_PAGE.value])
    if NAVIGATION_WIDGET_KEY not in state:
        state[NAVIGATION_WIDGET_KEY] = current.value
    with st.sidebar:
        st.markdown("## RetailFlow Analytics")
        st.caption("Management reporting workspace")
        selected = st.radio(
            "Navigation",
            labels,
            key=NAVIGATION_WIDGET_KEY,
            label_visibility="collapsed",
        )
    page = AppPage(selected)
    navigate_to(state, page)
    return page


def navigate_and_rerun(state: SessionState, page: AppPage) -> None:
    """Navigate from a page action and synchronize the sidebar widget."""
    navigate_to(state, page)
    state[NAVIGATION_WIDGET_KEY] = page.value
    st.rerun()


def render_placeholder(page: AppPage, state: SessionState) -> None:
    """Render a polished placeholder for a deliberately unfinished destination."""
    item = next(item for item in NAVIGATION_ITEMS if item.page is page)
    render_page_header(
        page_title=page.value,
        description=item.description,
        reporting_period=state[StateKey.SELECTED_REPORTING_PERIOD.value],
        last_successful_run=state[StateKey.LAST_SUCCESSFUL_RUN.value],
        status=state[StateKey.APPLICATION_STATUS.value],
    )
    render_empty_state(
        "This workspace is coming next",
        "This page is included in the application shell but its workflow is not enabled yet.",
    )
