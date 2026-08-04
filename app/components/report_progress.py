"""Streamlit progress presentation for report generation."""

from collections.abc import Callable

import streamlit as st

from app.services.report_service import ReportProgressEvent


def create_report_progress() -> Callable[[ReportProgressEvent], None]:
    """Create a callback that displays all seven generation stages."""
    status = st.status("Preparing report...", expanded=True)
    progress = st.progress(0.0)

    def update(event: ReportProgressEvent) -> None:
        status.write(f"{event.step}. {event.label}")
        progress.progress(event.fraction)
        if event.step == event.total_steps:
            status.update(label="Report generated", state="complete", expanded=False)

    return update


__all__ = ["create_report_progress"]
