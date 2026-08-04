"""Reusable empty-state presentation."""

import streamlit as st


def render_empty_state(title: str, message: str) -> None:
    """Render a clear non-error state when no records are available."""
    with st.container():
        st.subheader(title)
        st.info(message)
