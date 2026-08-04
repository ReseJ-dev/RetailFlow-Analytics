"""Compose and inject the local Streamlit stylesheet exactly once per app render."""

from __future__ import annotations

import logging
from pathlib import Path

import streamlit as st

from app.styles.tokens import DESIGN_TOKENS, DesignTokens, css_custom_properties

logger = logging.getLogger("retailflow.app.styles")

DEFAULT_STYLESHEET = Path(__file__).resolve().parents[1] / "styles.css"


def build_global_css(
    css_path: Path = DEFAULT_STYLESHEET,
    *,
    tokens: DesignTokens = DESIGN_TOKENS,
) -> str:
    """Combine generated token variables with the single local stylesheet.

    A missing stylesheet is non-fatal so the explicit Streamlit theme can continue to
    provide readable defaults. The technical path is retained in application logs.
    """
    try:
        stylesheet = css_path.read_text(encoding="utf-8")
    except OSError as error:
        logger.warning("Could not load application stylesheet '%s': %s", css_path, error)
        stylesheet = ""
    return f"{css_custom_properties(tokens)}\n\n{stylesheet}".rstrip()


def apply_global_theme(css_path: Path = DEFAULT_STYLESHEET) -> None:
    """Inject the composed local theme from the application entry point."""
    css = build_global_css(css_path)
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


__all__ = ["DEFAULT_STYLESHEET", "apply_global_theme", "build_global_css"]
