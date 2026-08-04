"""Shared page-header component."""

from datetime import datetime

import streamlit as st

from app.components.status_badge import render_status_badge
from app.state import ApplicationStatus


def _display_datetime(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone().strftime("%Y-%m-%d %H:%M")
    return str(value) if value else "No successful runs yet"


def render_page_header(
    *,
    page_title: str,
    description: str,
    reporting_period: object,
    last_successful_run: object,
    status: ApplicationStatus | str,
) -> None:
    """Render consistent product identity and workflow context for every page."""
    st.caption("RETAILFLOW ANALYTICS")
    st.title(page_title)
    st.write(description)
    period_column, run_column, status_column = st.columns(3)
    with period_column:
        st.caption("SELECTED REPORTING PERIOD")
        st.write(str(reporting_period) if reporting_period else "Not selected")
    with run_column:
        st.caption("LAST SUCCESSFUL RUN")
        st.write(_display_datetime(last_successful_run))
    with status_column:
        st.caption("CURRENT STATUS")
        render_status_badge(status)
