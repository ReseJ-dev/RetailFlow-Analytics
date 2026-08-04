"""Grouped validation-issue summary component."""

import streamlit as st

from app.services.processing_service import IssueGroupSummary


def render_issue_groups(groups: tuple[IssueGroupSummary, ...]) -> None:
    """Render actionable summaries for every non-empty issue category."""
    st.subheader("Issue categories")
    if not groups:
        st.success("No validation issues were found in the uploaded datasets.")
        return
    for group in groups:
        with st.expander(
            f"{group.category.value} · {group.affected_rows} affected rows · "
            f"{group.highest_severity.value.title()}"
        ):
            st.write(group.explanation)
            st.write(f"**Recommended action:** {group.recommended_action}")
