"""Shared page-header component."""

from datetime import datetime

import streamlit as st

from app.state import ApplicationStatus


def _display_datetime(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone().strftime("%Y-%m-%d %H:%M")
    return str(value) if value else "No successful runs yet"


def _display_status(value: ApplicationStatus | str) -> str:
    try:
        return ApplicationStatus(value).value
    except ValueError:
        return ApplicationStatus.FAILED.value


def render_page_context(
    *,
    reporting_period: object = None,
    last_successful_run: object = None,
    status: ApplicationStatus | str | None = None,
) -> None:
    """Render optional workflow context in one compact, readable line."""
    context: list[str] = []
    if reporting_period:
        context.append(f"Period: {reporting_period}")
    if last_successful_run:
        context.append(f"Last run: {_display_datetime(last_successful_run)}")
    if status is not None:
        context.append(f"Status: {_display_status(status)}")
    if context:
        st.caption("  ·  ".join(context))


def render_page_header(
    *,
    page_title: str,
    description: str,
    reporting_period: object,
    last_successful_run: object,
    status: ApplicationStatus | str,
) -> None:
    """Render a compact title, description, and optional workflow context."""
    st.caption(f"RetailFlow / {page_title}")
    st.title(page_title)
    st.write(description)
    render_page_context(
        reporting_period=reporting_period,
        last_successful_run=last_successful_run,
        status=status,
    )
