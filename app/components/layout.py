"""Branded application shell, central navigation, and placeholder layout."""

from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from app.components.empty_state import render_empty_state
from app.components.header import render_page_header
from app.state import AppPage, SessionState, StateKey, initialize_state, navigate_to
from app.styles.theme import apply_global_theme

_BRAND_MARKUP = """
<div class="rf-brand" aria-label="RetailFlow Analytics">
  <span class="rf-brand-mark" aria-hidden="true"><span></span></span>
  <span class="rf-brand-copy">
    <strong>RetailFlow</strong>
    <span>Analytics</span>
  </span>
</div>
<p class="rf-brand-caption">Management reporting workspace</p>
"""


@dataclass(frozen=True, slots=True)
class NavigationItem:
    """One centrally-defined application destination."""

    page: AppPage
    icon: str
    description: str
    implemented: bool = False


PRIMARY_NAVIGATION_ITEMS = (
    NavigationItem(
        AppPage.OVERVIEW,
        ":material/home:",
        "Start a report and review recent activity.",
        True,
    ),
    NavigationItem(
        AppPage.UPLOAD_DATA,
        ":material/upload_file:",
        "Upload and map source datasets.",
        True,
    ),
    NavigationItem(
        AppPage.DATA_QUALITY,
        ":material/fact_check:",
        "Review validation results and exclusions.",
        True,
    ),
    NavigationItem(
        AppPage.DASHBOARD,
        ":material/space_dashboard:",
        "Explore sales, returns, and inventory analytics.",
        True,
    ),
    NavigationItem(
        AppPage.GENERATE_REPORT,
        ":material/description:",
        "Configure and create an Excel report.",
        True,
    ),
    NavigationItem(
        AppPage.RUN_HISTORY,
        ":material/history:",
        "Review previous processing runs.",
        True,
    ),
)

SECONDARY_NAVIGATION_ITEMS = (
    NavigationItem(
        AppPage.SETTINGS,
        ":material/settings:",
        "Manage report and validation preferences.",
        True,
    ),
)

NAVIGATION_ITEMS = PRIMARY_NAVIGATION_ITEMS + SECONDARY_NAVIGATION_ITEMS


def load_local_css(css_path: Path) -> None:
    """Apply the shared theme while preserving the existing application helper API."""
    apply_global_theme(css_path)


def render_navigation_item(
    state: SessionState,
    item: NavigationItem,
    *,
    current_page: AppPage,
) -> None:
    """Render one dependency-free icon button backed by canonical page state."""
    st.button(
        item.page.value,
        key=f"navigation_{item.page.name.casefold()}",
        help=item.description,
        on_click=navigate_to,
        args=(state, item.page),
        type="primary" if item.page is current_page else "tertiary",
        icon=item.icon,
        width="stretch",
    )


def render_sidebar(state: SessionState) -> None:
    """Render product branding and the only visible application navigation."""
    current = AppPage(state[StateKey.CURRENT_PAGE.value])
    with st.sidebar:
        st.markdown(_BRAND_MARKUP, unsafe_allow_html=True)
        st.caption("WORKSPACE")
        for item in PRIMARY_NAVIGATION_ITEMS:
            render_navigation_item(state, item, current_page=current)
        st.divider()
        st.caption("PREFERENCES")
        for item in SECONDARY_NAVIGATION_ITEMS:
            render_navigation_item(state, item, current_page=current)


def render_app_shell(state: SessionState) -> AppPage:
    """Render the shared sidebar and return the canonical active page."""
    initialize_state(state)
    render_sidebar(state)
    return AppPage(state[StateKey.CURRENT_PAGE.value])


def render_navigation(state: SessionState) -> AppPage:
    """Compatibility wrapper for the previous shell entry point."""
    return render_app_shell(state)


def navigate_and_rerun(state: SessionState, page: AppPage) -> None:
    """Navigate from an in-page workflow action and rerun the active script."""
    navigate_to(state, page)
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
