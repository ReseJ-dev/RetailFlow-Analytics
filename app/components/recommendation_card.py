"""Rule-based recommendation cards and filters."""

from collections.abc import Mapping

import streamlit as st

from app.components.ui import StatusVariant, section_header, status_badge
from retailflow.analytics import Recommendation

_GROUPS = (
    ("Critical", "critical", StatusVariant.ERROR),
    ("Needs Attention", "warning", StatusVariant.WARNING),
    ("Opportunity", "info", StatusVariant.INFORMATION),
)


def _metric_summary(metrics: Mapping[str, object]) -> str:
    return " · ".join(
        f"{str(name).replace('_', ' ').title()}: {value}"
        for name, value in metrics.items()
        if value is not None
    )


def _render_recommendation(recommendation: Recommendation) -> None:
    variant = {
        "critical": StatusVariant.ERROR,
        "warning": StatusVariant.WARNING,
        "info": StatusVariant.INFORMATION,
    }[recommendation.severity.value]
    with st.container(border=True):
        label, badge = st.columns([3, 1])
        with label:
            st.markdown(f"**{recommendation.recommendation_type.value.title()}**")
            if recommendation.product_id:
                st.caption(f"Product: {recommendation.product_id}")
        with badge:
            status_badge(recommendation.severity.value.title(), variant)
        st.write(recommendation.explanation)
        metrics = _metric_summary(recommendation.supporting_metrics)
        if metrics:
            st.caption(f"Supporting metrics · {metrics}")
        st.markdown("**Recommended action**")
        st.write(recommendation.recommended_action)
        st.caption(f"Rule: {recommendation.rule_identifier}")


def render_recommendations(recommendations: tuple[Recommendation, ...]) -> None:
    """Filter and display transparent recommendation rules with supporting metrics."""
    section_header(
        "Recommendations",
        "Generated from transparent business rules, not generative AI.",
    )
    if not recommendations:
        st.info("No recommendations were generated for the selected filters.")
        return
    severities = sorted({item.severity.value for item in recommendations})
    types = sorted({item.recommendation_type.value for item in recommendations})
    controls = st.columns([2, 2, 1])
    selected_severities = controls[0].multiselect(
        "Recommendation severity", severities, default=severities
    )
    selected_types = controls[1].multiselect("Recommendation type", types, default=types)
    top_priority = controls[2].checkbox("Top-priority only", value=False)
    filtered = [
        item
        for item in recommendations
        if item.severity.value in selected_severities
        and item.recommendation_type.value in selected_types
        and (not top_priority or item.severity.value == "critical")
    ]
    if not filtered:
        st.info("No recommendations match the selected recommendation filters.")
        return
    visible_groups = _GROUPS[:1] if top_priority else _GROUPS
    tabs = st.tabs(
        [
            f"{title} ({sum(item.severity.value == severity for item in filtered)})"
            for title, severity, _ in visible_groups
        ]
    )
    for tab, (title, severity, variant) in zip(tabs, visible_groups, strict=True):
        with tab:
            grouped = [item for item in filtered if item.severity.value == severity]
            status_badge(
                f"{len(grouped)} {title.casefold()}",
                variant if grouped else StatusVariant.NEUTRAL,
                accessible_label=f"{title} recommendations: {len(grouped)}",
            )
            if not grouped:
                st.info(f"No {title.casefold()} recommendations match the current filters.")
                continue
            for recommendation in grouped:
                _render_recommendation(recommendation)
