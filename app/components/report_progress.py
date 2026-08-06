"""Streamlit progress presentation for report generation."""

from collections.abc import Callable

import streamlit as st

from app.services.report_service import ReportProgressEvent


def create_report_progress() -> Callable[[ReportProgressEvent], None]:
    """Display only progress events emitted by the report service."""
    status = st.status("Preparing report...", expanded=True)
    progress = st.progress(0.0)

    def update(event: ReportProgressEvent) -> None:
        status.update(
            label=f"{event.label} ({event.step} of {event.total_steps})",
            state="running" if event.step < event.total_steps else "complete",
            expanded=event.step < event.total_steps,
        )
        status.write(event.label)
        progress.progress(event.fraction, text=event.label)
        if event.step == event.total_steps:
            status.update(label="Report generated", state="complete", expanded=False)

    return update


__all__ = ["create_report_progress"]
