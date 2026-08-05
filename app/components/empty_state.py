"""Backward-compatible empty-state adapter."""

from app.components.ui import empty_state


def render_empty_state(title: str, message: str) -> None:
    """Render a clear non-error state when no records are available."""
    empty_state(title, message)
