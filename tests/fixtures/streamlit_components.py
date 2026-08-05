"""Small Streamlit fixture exercising shared UI primitives."""

import streamlit as st
from app.components.ui import (
    ActionSpec,
    StatusVariant,
    action_bar,
    callout,
    chart_container,
    data_source_status,
    empty_state,
    information_card,
    issue_summary_card,
    metric_card,
    page_header,
    section_header,
    status_badge,
    workflow_progress,
)

page_header("Component preview", "Shared visual primitives", context=("Status: Ready",))
section_header("Summary", "Presentation only")
metric_card("Net Revenue", "€1,250", delta="4.2%")
status_badge("Ready", StatusVariant.SUCCESS)
callout("Check complete", "All required fields are present.", StatusVariant.INFORMATION)
empty_state("No returns", "No return records match the current filters.", compact=True)
workflow_progress(("Upload", "Validate", "Report"), 2)
information_card("Source files", "Two required datasets loaded.")
with chart_container("Revenue over time", "Daily net revenue"):
    st.write("Chart placeholder")
action_bar((ActionSpec("continue", "Continue", button_type="primary"),))
data_source_status("Orders", "Loaded", variant=StatusVariant.SUCCESS, row_count=24)
issue_summary_card(
    "Missing Values",
    2,
    StatusVariant.WARNING,
    "Some optional values are missing.",
    "Review the affected fields.",
)
