"""Filterable, traceable, and privacy-conscious validation issue table."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import ceil

import pandas as pd
import streamlit as st

from app.components.issue_group import display_category_name
from app.components.ui import StatusVariant, empty_state, section_header, status_badge
from app.services.processing_service import (
    QualityIssueCategory,
    categorize_issue,
    issue_identifier,
)
from retailflow.validation import ValidationIssue, ValidationSeverity

_SENSITIVE_FIELD_TOKENS = ("customer", "email", "token", "secret", "password")
_SEVERITY_VARIANTS = {
    ValidationSeverity.INFO: StatusVariant.INFORMATION,
    ValidationSeverity.WARNING: StatusVariant.WARNING,
    ValidationSeverity.ERROR: StatusVariant.ERROR,
}


@dataclass(frozen=True, slots=True)
class IssueView:
    """One validation issue enriched only with presentation metadata."""

    occurrence: int
    issue: ValidationIssue
    category: QualityIssueCategory
    action_taken: str
    processing_status: str


@dataclass(frozen=True, slots=True)
class IssueFilters:
    """Immutable presentation filters that never alter validation results."""

    datasets: tuple[str, ...] = ()
    severities: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()
    filenames: tuple[str, ...] = ()
    processing_statuses: tuple[str, ...] = ()
    search: str = ""


def _processing_status(issue: ValidationIssue, action: str) -> str:
    if (
        issue.severity is ValidationSeverity.ERROR
        and issue.row_number is None
        and not issue.row_can_continue
    ):
        return "Blocking — source correction required"
    if action == "Excluded from processing":
        return "Excluded from processing"
    if action == "Accepted with warning":
        return "Accepted with warning"
    if not issue.row_can_continue:
        return "Exclusion required"
    if issue.severity is ValidationSeverity.WARNING:
        return "Reviewable warning"
    return "Can continue"


def build_issue_views(
    issues: Sequence[ValidationIssue],
    actions: Mapping[str, str] | None = None,
) -> tuple[IssueView, ...]:
    """Attach existing categories and decisions to issues without mutating them."""
    action_mapping = actions or {}
    views: list[IssueView] = []
    for occurrence, issue in enumerate(issues):
        action = action_mapping.get(issue_identifier(issue, occurrence), "Pending review")
        views.append(
            IssueView(
                occurrence,
                issue,
                categorize_issue(issue),
                action,
                _processing_status(issue, action),
            )
        )
    return tuple(views)


def _field_label(issue: ValidationIssue) -> str:
    return issue.field or "Not applicable"


def _filename_label(issue: ValidationIssue) -> str:
    return issue.source_filename or "Not available"


def _safe_original_value(issue: ValidationIssue) -> str:
    field = (issue.field or "").casefold()
    if any(token in field for token in _SENSITIVE_FIELD_TOKENS):
        return "[REDACTED]"
    return str(issue.original_value)


def _searchable_text(view: IssueView) -> str:
    issue = view.issue
    return " ".join(
        (
            issue.source_dataset.value,
            _filename_label(issue),
            _field_label(issue),
            issue.issue_code,
            issue.message,
            _safe_original_value(issue),
            issue.recommended_action,
            display_category_name(view.category),
            view.processing_status,
        )
    ).casefold()


def filter_issue_views(
    views: Sequence[IssueView],
    filters: IssueFilters,
) -> tuple[IssueView, ...]:
    """Return a filtered view while preserving the original issue collection."""
    search = filters.search.strip().casefold()
    return tuple(
        view
        for view in views
        if (not filters.datasets or view.issue.source_dataset.value in filters.datasets)
        and (not filters.severities or view.issue.severity.value in filters.severities)
        and (not filters.categories or display_category_name(view.category) in filters.categories)
        and (not filters.fields or _field_label(view.issue) in filters.fields)
        and (not filters.filenames or _filename_label(view.issue) in filters.filenames)
        and (
            not filters.processing_statuses or view.processing_status in filters.processing_statuses
        )
        and (not search or search in _searchable_text(view))
    )


def _options(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _render_filters(views: tuple[IssueView, ...]) -> IssueFilters:
    first_row = st.columns(3)
    datasets = first_row[0].multiselect(
        "Dataset",
        _options(tuple(view.issue.source_dataset.value for view in views)),
        key="quality_filter_dataset",
    )
    severities = first_row[1].multiselect(
        "Severity",
        _options(tuple(view.issue.severity.value for view in views)),
        key="quality_filter_severity",
    )
    categories = first_row[2].multiselect(
        "Issue category",
        _options(tuple(display_category_name(view.category) for view in views)),
        key="quality_filter_category",
    )
    second_row = st.columns(3)
    fields = second_row[0].multiselect(
        "Field",
        _options(tuple(_field_label(view.issue) for view in views)),
        key="quality_filter_field",
    )
    filenames = second_row[1].multiselect(
        "Filename",
        _options(tuple(_filename_label(view.issue) for view in views)),
        key="quality_filter_filename",
    )
    statuses = second_row[2].multiselect(
        "Processing status",
        _options(tuple(view.processing_status for view in views)),
        key="quality_filter_status",
    )
    search = st.text_input(
        "Search issues",
        placeholder="Search issue code, message, value, or recommended action",
        key="quality_filter_search",
    )
    return IssueFilters(
        tuple(datasets),
        tuple(severities),
        tuple(categories),
        tuple(fields),
        tuple(filenames),
        tuple(statuses),
        search,
    )


def _preview(value: str, limit: int = 90) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


def _table_frame(views: Sequence[IssueView]) -> pd.DataFrame:
    records = []
    severity_symbols = {
        ValidationSeverity.INFO: "INFO",
        ValidationSeverity.WARNING: "WARNING",
        ValidationSeverity.ERROR: "ERROR",
    }
    for view in views:
        issue = view.issue
        records.append(
            {
                "Severity": severity_symbols[issue.severity],
                "Dataset": issue.source_dataset.value,
                "Source Filename": _filename_label(issue),
                "Source Row": issue.row_number if issue.row_number is not None else "Dataset-level",
                "Field": _field_label(issue),
                "Issue Code": issue.issue_code,
                "Issue": issue.message,
                "Original Value": _preview(_safe_original_value(issue)),
                "Recommended Action": issue.recommended_action,
                "Continuation Status": view.processing_status,
            }
        )
    return pd.DataFrame.from_records(records)


def _render_detail(view: IssueView) -> None:
    issue = view.issue
    row_label = issue.row_number if issue.row_number is not None else "dataset-level"
    with st.expander(
        f"{issue.severity.value.title()} · {issue.source_dataset.value} · "
        f"{issue.issue_code} · row {row_label}"
    ):
        status_badge(
            issue.severity.value.title(),
            _SEVERITY_VARIANTS[issue.severity],
            accessible_label=f"Issue severity: {issue.severity.value}",
        )
        st.write(f"**Dataset:** {issue.source_dataset.value}")
        st.write(f"**Source filename:** {_filename_label(issue)}")
        st.write(f"**Source row:** {row_label}")
        st.write(f"**Field:** {_field_label(issue)}")
        st.write(f"**Issue code:** {issue.issue_code}")
        st.write(f"**Issue:** {issue.message}")
        st.caption("Original value (full field value; sensitive fields are redacted)")
        st.code(_safe_original_value(issue), language=None, wrap_lines=True)
        st.write(f"**Recommended action:** {issue.recommended_action}")
        st.write(f"**Continuation status:** {view.processing_status}")
        st.write(f"**Action taken:** {view.action_taken}")


def render_issue_table(
    issues: tuple[ValidationIssue, ...], actions: Mapping[str, str] | None = None
) -> None:
    """Render six filters, a scrollable table, and paginated complete details."""
    section_header(
        "Issue details",
        "Presentation filters do not modify or rerun validation.",
    )
    views = build_issue_views(issues, actions)
    if not views:
        empty_state(
            "No validation issues",
            "The processed datasets contain no warning or error records to review.",
            compact=True,
        )
        return
    filtered = filter_issue_views(views, _render_filters(views))
    if not filtered:
        empty_state(
            "No issues match these filters",
            "Adjust or clear the presentation filters to see validation issues.",
            compact=True,
        )
        st.caption(f"Showing 0 of {len(views):,} issues.")
        return
    st.dataframe(
        _table_frame(filtered),
        hide_index=True,
        width="stretch",
        height=460,
        row_height=36,
        column_config={
            "Severity": st.column_config.TextColumn(width="small"),
            "Dataset": st.column_config.TextColumn(width="small"),
            "Source Row": st.column_config.TextColumn(width="small"),
            "Issue": st.column_config.TextColumn(width="large"),
            "Recommended Action": st.column_config.TextColumn(width="large"),
            "Continuation Status": st.column_config.TextColumn(width="medium"),
        },
    )
    st.caption(
        f"Showing {len(filtered):,} of {len(views):,} issues. "
        "Open a detail panel below to inspect complete values and recommendations."
    )
    controls = st.columns([1, 1, 3])
    page_size = controls[0].selectbox(
        "Details per page",
        (25, 50, 100),
        key="quality_detail_page_size",
    )
    page_count = max(1, ceil(len(filtered) / page_size))
    page_key = "quality_detail_page"
    stored_page = int(st.session_state.get(page_key, 1))
    if stored_page > page_count:
        st.session_state[page_key] = 1
    page = controls[1].number_input(
        "Detail page",
        min_value=1,
        max_value=page_count,
        value=1,
        step=1,
        key=page_key,
    )
    start = (page - 1) * page_size
    st.caption(f"Detail page {page} of {page_count}")
    for view in filtered[start : start + page_size]:
        _render_detail(view)


__all__ = [
    "IssueFilters",
    "IssueView",
    "build_issue_views",
    "filter_issue_views",
    "render_issue_table",
]
