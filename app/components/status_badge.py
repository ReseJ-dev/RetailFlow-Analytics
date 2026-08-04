"""Reusable application-status badge."""

import streamlit as st

from app.state import ApplicationStatus

_STATUS_COLOURS = {
    ApplicationStatus.READY: "green",
    ApplicationStatus.WAITING_FOR_DATA: "gray",
    ApplicationStatus.VALIDATING: "orange",
    ApplicationStatus.PROCESSING: "blue",
    ApplicationStatus.REPORT_GENERATED: "green",
    ApplicationStatus.FAILED: "red",
}


def render_status_badge(status: ApplicationStatus | str) -> None:
    """Render a restrained status label using only trusted application values."""
    try:
        resolved = ApplicationStatus(status)
    except ValueError:
        resolved = ApplicationStatus.FAILED
    st.markdown(f"**Status:** :{_STATUS_COLOURS[resolved]}[{resolved.value}]")
