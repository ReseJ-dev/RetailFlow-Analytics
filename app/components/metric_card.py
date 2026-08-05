"""Backward-compatible metric-card adapter."""

from app.components.ui import metric_card


def render_metric_card(label: str, value: str | int, *, help_text: str | None = None) -> None:
    """Render an accessible metric with an optional explanatory tooltip."""
    metric_card(label, value, help_text=help_text)
