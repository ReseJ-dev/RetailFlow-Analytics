"""Rule-based recommendation cards and filters."""

import streamlit as st

from retailflow.analytics import Recommendation


def render_recommendations(recommendations: tuple[Recommendation, ...]) -> None:
    """Filter and display transparent recommendation rules with supporting metrics."""
    st.subheader("Recommendations")
    st.caption("Recommendations are generated from transparent business rules, not generative AI.")
    if not recommendations:
        st.info("No recommendations were generated for the selected filters.")
        return
    severities = sorted({item.severity.value for item in recommendations})
    types = sorted({item.recommendation_type.value for item in recommendations})
    controls = st.columns(3)
    selected_severities = controls[0].multiselect(
        "Recommendation severity", severities, default=severities
    )
    selected_types = controls[1].multiselect("Recommendation type", types, default=types)
    top_priority = controls[2].checkbox("Top-priority view", value=True)
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
    for recommendation in filtered:
        with st.container(border=True):
            st.markdown(
                f"**{recommendation.severity.value.title()} · "
                f"{recommendation.recommendation_type.value.title()}**"
            )
            if recommendation.product_id:
                st.caption(f"Product: {recommendation.product_id}")
            st.write(recommendation.explanation)
            st.write(f"**Recommended action:** {recommendation.recommended_action}")
            with st.expander("Supporting metrics and rule"):
                st.json(dict(recommendation.supporting_metrics))
                st.code(recommendation.rule_identifier, language=None)
