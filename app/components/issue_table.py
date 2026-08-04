"""Filterable, privacy-conscious validation issue table."""

from collections.abc import Mapping

import pandas as pd
import streamlit as st

from app.services.processing_service import issues_dataframe
from retailflow.validation import ValidationIssue


def _options(frame: pd.DataFrame, column: str) -> list[str]:
    if frame.empty or column not in frame:
        return []
    return sorted(str(value) for value in frame[column].dropna().unique())


def _apply_filters(frame: pd.DataFrame) -> pd.DataFrame:
    filter_columns = st.columns(4)
    selections = {
        "severity": filter_columns[0].multiselect("Severity", _options(frame, "severity")),
        "source_dataset": filter_columns[1].multiselect(
            "Source dataset", _options(frame, "source_dataset")
        ),
        "issue_code": filter_columns[2].multiselect("Issue code", _options(frame, "issue_code")),
        "field": filter_columns[3].multiselect("Field", _options(frame, "field")),
    }
    filtered = frame.copy()
    for column, selected in selections.items():
        if selected:
            filtered = filtered.loc[filtered[column].astype(str).isin(selected)]
    search = st.text_input(
        "Search issue details",
        placeholder="Search by file, field, issue, or recommended action",
    ).strip()
    if search:
        searchable = filtered.fillna("").astype(str).agg(" ".join, axis=1)
        filtered = filtered.loc[searchable.str.contains(search, case=False, regex=False)]
    return filtered


def render_issue_table(
    issues: tuple[ValidationIssue, ...], actions: Mapping[str, str] | None = None
) -> None:
    """Render filters, safe issue columns, and expandable row-level details."""
    st.subheader("Issue details")
    frame = issues_dataframe(issues, actions)
    if frame.empty:
        st.info("No issue details are available for the current validation result.")
        return
    filtered = _apply_filters(frame)
    st.dataframe(
        filtered[
            [
                "severity",
                "source_file",
                "row_number",
                "field",
                "issue",
                "original_value",
                "recommended_action",
                "action_taken",
            ]
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(f"Showing {len(filtered):,} of {len(frame):,} issues.")
    for index, row in filtered.head(50).iterrows():
        with st.expander(
            f"{str(row['severity']).title()} · {row['source_dataset']} · "
            f"{row['issue_code']} · row {row['row_number'] or 'dataset'}"
        ):
            st.write(f"**Field:** {row['field'] or 'Not applicable'}")
            st.write(f"**Issue:** {row['issue']}")
            st.write(f"**Original value:** {row['original_value']}")
            st.write(f"**Recommended action:** {row['recommended_action']}")
            st.write(f"**Action taken:** {row['action_taken']}")
            st.caption(f"Issue reference: {index}")
