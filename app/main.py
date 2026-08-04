"""Streamlit application entry point for RetailFlow Analytics."""

from __future__ import annotations

import logging
from pathlib import Path

import streamlit as st

from app.components.layout import load_local_css, render_navigation, render_placeholder
from app.pages.dashboard import render_dashboard
from app.pages.data_quality import render_data_quality
from app.pages.overview import render_overview
from app.state import AppPage, initialize_state

logger = logging.getLogger("retailflow.app")

_USER_ERROR_MESSAGE = (
    "RetailFlow could not complete this action. Please try again or review the application logs."
)


def _render_application() -> None:
    """Render the selected destination while keeping unfinished workflows graceful."""
    initialize_state(st.session_state)
    page = render_navigation(st.session_state)
    if page is AppPage.OVERVIEW:
        render_overview(st.session_state)
    elif page is AppPage.DATA_QUALITY:
        render_data_quality(st.session_state)
    elif page is AppPage.DASHBOARD:
        render_dashboard(st.session_state)
    else:
        render_placeholder(page, st.session_state)


def main() -> None:
    """Configure and safely render the RetailFlow Streamlit application."""
    st.set_page_config(
        page_title="RetailFlow Analytics",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    load_local_css(Path(__file__).with_name("styles.css"))
    try:
        _render_application()
    except Exception:
        logger.exception("Unexpected error while rendering the Streamlit application")
        st.error(_USER_ERROR_MESSAGE)


if __name__ == "__main__":
    main()
