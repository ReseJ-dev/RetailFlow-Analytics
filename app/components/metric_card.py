"""Small metric-card component."""

import streamlit as st


def render_metric_card(label: str, value: str | int, *, help_text: str | None = None) -> None:
    """Render an accessible metric with an optional explanatory tooltip."""
    st.metric(label=label, value=value, help=help_text)
