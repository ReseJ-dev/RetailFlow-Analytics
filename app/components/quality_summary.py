"""Compact data-quality health summary."""

import streamlit as st

from app.components.ui import StatusVariant, metric_card, status_badge
from app.services.processing_service import DataQualitySummary


def quality_score_interpretation(score: float) -> tuple[str, StatusVariant]:
    """Return a textual, presentation-only interpretation of the existing score."""
    if score >= 95:
        return "Excellent data health", StatusVariant.SUCCESS
    if score >= 85:
        return "Good data health", StatusVariant.SUCCESS
    if score >= 70:
        return "Review recommended", StatusVariant.WARNING
    return "Significant issues require attention", StatusVariant.ERROR


def render_quality_summary(
    summary: DataQualitySummary,
    *,
    clean_rows: int | None = None,
    warning_rows: int | None = None,
    blocking_errors: int | None = None,
) -> None:
    """Render the existing score and row health counts without recalculating them."""
    interpretation, variant = quality_score_interpretation(summary.quality_score)
    resolved_clean_rows = summary.valid_rows if clean_rows is None else clean_rows
    resolved_warning_rows = summary.warnings if warning_rows is None else warning_rows
    resolved_blocking_errors = summary.errors if blocking_errors is None else blocking_errors
    columns = st.columns(6)
    with columns[0]:
        metric_card(
            "Overall Quality Score",
            f"{summary.quality_score:.1f}%",
            help_text="Existing rule-based data-quality score; this is not an AI score.",
        )
        status_badge(
            interpretation,
            variant,
            accessible_label=f"Quality score interpretation: {interpretation}",
        )
    metrics: tuple[tuple[str, int], ...] = (
        ("Total Rows", summary.source_rows),
        ("Clean Rows", resolved_clean_rows),
        ("Warning Rows", resolved_warning_rows),
        ("Excluded Rows", summary.excluded_rows),
        ("Blocking Errors", resolved_blocking_errors),
    )
    for column, (label, value) in zip(columns[1:], metrics, strict=True):
        with column:
            metric_card(label, value)
    st.caption(
        "The score uses the existing rule-based formula: clean rows receive full credit, "
        "warning-only rows receive half credit, and error rows receive no credit. "
        "Blocking Errors counts dataset-level structural errors that prevent continuation."
    )


__all__ = ["quality_score_interpretation", "render_quality_summary"]
