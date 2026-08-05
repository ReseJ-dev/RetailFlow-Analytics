"""Grouped validation-issue summary cards."""

import streamlit as st

from app.components.ui import StatusVariant, information_card, issue_summary_card, section_header
from app.services.processing_service import (
    IssueGroupSummary,
    QualityIssueCategory,
)
from retailflow.validation import ValidationSeverity

_CATEGORY_LABELS = {
    QualityIssueCategory.MISSING_REQUIRED_COLUMNS: "Missing Columns",
    QualityIssueCategory.MISSING_VALUES: "Missing Values",
    QualityIssueCategory.DUPLICATE_RECORDS: "Duplicates",
    QualityIssueCategory.INVALID_DATA_TYPES: "Invalid Types",
    QualityIssueCategory.INVALID_RELATIONSHIPS: "Relationship Errors",
    QualityIssueCategory.BUSINESS_RULE_VIOLATIONS: "Business Rule Violations",
    QualityIssueCategory.TRANSFORMATION_WARNINGS: "Transformation Warnings",
}
_SEVERITY_VARIANTS = {
    ValidationSeverity.INFO: StatusVariant.INFORMATION,
    ValidationSeverity.WARNING: StatusVariant.WARNING,
    ValidationSeverity.ERROR: StatusVariant.ERROR,
}


def display_category_name(category: QualityIssueCategory) -> str:
    """Return the concise page label without changing service classification."""
    return _CATEGORY_LABELS[category]


def _render_group(group: IssueGroupSummary | None, category: QualityIssueCategory) -> None:
    label = display_category_name(category)
    if group is None:
        information_card(
            label,
            "No issues detected in this category.",
            label="0 AFFECTED ROWS",
        )
        return
    issue_summary_card(
        label,
        group.affected_rows,
        _SEVERITY_VARIANTS[group.highest_severity],
        group.explanation,
        group.recommended_action,
    )


def render_issue_groups(groups: tuple[IssueGroupSummary, ...]) -> None:
    """Render all seven stable issue categories, including intentional empty states."""
    section_header(
        "Issue categories",
        "Classification uses the existing validation issue rules.",
    )
    by_category = {group.category: group for group in groups}
    categories = tuple(QualityIssueCategory)
    for start, width in ((0, 4), (4, 3)):
        category_slice = categories[start : start + width]
        for column, category in zip(st.columns(width), category_slice, strict=True):
            with column:
                _render_group(by_category.get(category), category)


__all__ = ["display_category_name", "render_issue_groups"]
