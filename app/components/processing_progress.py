"""Streamlit progress renderer for pipeline execution."""

from collections.abc import Callable

import streamlit as st

from app.services.processing_service import ProcessingProgressEvent


def create_processing_progress() -> Callable[[ProcessingProgressEvent], None]:
    """Create a callback that updates one status message and progress bar."""
    status = st.empty()
    progress_bar = st.progress(0.0)

    def update(event: ProcessingProgressEvent) -> None:
        status.write(f"**{event.label}** ({event.step}/{event.total_steps})")
        progress_bar.progress(event.fraction)

    return update
