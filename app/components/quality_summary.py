"""Data-quality summary metrics component."""

import streamlit as st

from app.components.metric_card import render_metric_card
from app.services.processing_service import DataQualitySummary


def render_quality_summary(summary: DataQualitySummary) -> None:
    """Render the six requested data-quality metrics and score explanation."""
    columns = st.columns(6)
    metrics: tuple[tuple[str, str | int], ...] = (
        ("Source rows processed", summary.source_rows),
        ("Valid rows", summary.valid_rows),
        ("Excluded rows", summary.excluded_rows),
        ("Warnings", summary.warnings),
        ("Errors", summary.errors),
        ("Quality score", f"{summary.quality_score:.1f}%"),
    )
    for column, (label, value) in zip(columns, metrics, strict=True):
        with column:
            render_metric_card(label, value)
    st.caption(
        "The data-quality score is rule-based, not an AI score. Clean rows receive full "
        "credit, warning-only rows receive half credit, and error rows receive no credit."
    )
