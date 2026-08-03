"""Validation result models and flat error-report export helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import pandas as pd

from retailflow.validation.schemas import DatasetType


class ValidationSeverity(StrEnum):
    """Severity assigned to a data-quality issue."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One actionable issue found in a source dataset."""

    severity: ValidationSeverity
    source_dataset: DatasetType
    source_filename: str | None
    row_number: int | None
    field: str | None
    issue_code: str
    message: str
    original_value: Any
    recommended_action: str
    row_can_continue: bool

    @property
    def can_continue(self) -> bool:
        """Compatibility alias for consumers rendering row-level status."""
        return self.row_can_continue


@dataclass(frozen=True, slots=True)
class DatasetValidationResult:
    """Validation outcome and quality metrics for one dataset."""

    dataset_type: DatasetType
    source_filename: str | None
    total_rows: int
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def error_count(self) -> int:
        return sum(issue.severity is ValidationSeverity.ERROR for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity is ValidationSeverity.WARNING for issue in self.issues)

    @property
    def info_count(self) -> int:
        return sum(issue.severity is ValidationSeverity.INFO for issue in self.issues)

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    @property
    def can_continue(self) -> bool:
        return not any(not issue.row_can_continue for issue in self.issues)

    def _row_buckets(self) -> tuple[set[int], set[int]]:
        if any(issue.row_number is None and not issue.row_can_continue for issue in self.issues):
            return set(range(self.total_rows)), set()
        error_rows = {
            issue.row_number
            for issue in self.issues
            if issue.row_number is not None
            and (issue.severity is ValidationSeverity.ERROR or not issue.row_can_continue)
        }
        warning_rows = {
            issue.row_number
            for issue in self.issues
            if issue.row_number is not None
            and issue.severity is ValidationSeverity.WARNING
            and issue.row_number not in error_rows
        }
        return error_rows, warning_rows

    @property
    def error_row_count(self) -> int:
        return len(self._row_buckets()[0])

    @property
    def warning_row_count(self) -> int:
        return len(self._row_buckets()[1])

    @property
    def valid_row_count(self) -> int:
        """Return rows with neither an error nor a warning."""
        return max(0, self.total_rows - self.error_row_count - self.warning_row_count)

    @property
    def quality_score(self) -> float:
        """Return a transparent 0–100 row-based data-quality score.

        Each clean row earns 1 point, each warning-only row earns 0.5 points, and
        each error/blocking row earns 0 points. Multiple issues on the same row do
        not compound the penalty. The score is ``earned / total_rows * 100``.
        An empty issue-free dataset scores 100; an empty invalid dataset scores 0.
        """
        if self.total_rows == 0:
            return 100.0 if not self.issues else 0.0
        earned_points = self.valid_row_count + 0.5 * self.warning_row_count
        return round(100.0 * earned_points / self.total_rows, 2)

    @property
    def data_quality_score(self) -> float:
        """Compatibility alias for reporting code."""
        return self.quality_score

    def issues_dataframe(self) -> pd.DataFrame:
        return issues_to_dataframe(self.issues)


@dataclass(frozen=True, slots=True)
class CombinedValidationResult:
    """Validation outcomes across all supplied datasets."""

    dataset_results: tuple[DatasetValidationResult, ...]

    @property
    def issues(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for result in self.dataset_results for issue in result.issues)

    @property
    def total_rows(self) -> int:
        return sum(result.total_rows for result in self.dataset_results)

    @property
    def error_count(self) -> int:
        return sum(result.error_count for result in self.dataset_results)

    @property
    def warning_count(self) -> int:
        return sum(result.warning_count for result in self.dataset_results)

    @property
    def valid_row_count(self) -> int:
        return sum(result.valid_row_count for result in self.dataset_results)

    @property
    def can_continue(self) -> bool:
        return all(result.can_continue for result in self.dataset_results)

    @property
    def quality_score(self) -> float:
        if not self.dataset_results:
            return 100.0
        if self.total_rows == 0:
            return round(
                sum(result.quality_score for result in self.dataset_results)
                / len(self.dataset_results),
                2,
            )
        weighted_score = sum(
            result.quality_score * result.total_rows for result in self.dataset_results
        )
        return round(weighted_score / self.total_rows, 2)

    @property
    def data_quality_score(self) -> float:
        return self.quality_score

    def result_for(self, dataset_type: DatasetType | str) -> DatasetValidationResult | None:
        normalized = DatasetType(dataset_type)
        return next(
            (result for result in self.dataset_results if result.dataset_type is normalized),
            None,
        )

    def issues_dataframe(self) -> pd.DataFrame:
        return issues_to_dataframe(self.issues)


ISSUE_REPORT_COLUMNS = (
    "severity",
    "source_dataset",
    "source_filename",
    "row_number",
    "field",
    "issue_code",
    "message",
    "original_value",
    "recommended_action",
    "row_can_continue",
)


def issues_to_dataframe(issues: Iterable[ValidationIssue]) -> pd.DataFrame:
    """Export issues as a flat DataFrame suitable for an Excel error worksheet."""
    records = [
        {
            "severity": issue.severity.value,
            "source_dataset": issue.source_dataset.value,
            "source_filename": issue.source_filename,
            "row_number": issue.row_number,
            "field": issue.field,
            "issue_code": issue.issue_code,
            "message": issue.message,
            "original_value": issue.original_value,
            "recommended_action": issue.recommended_action,
            "row_can_continue": issue.row_can_continue,
        }
        for issue in issues
    ]
    return pd.DataFrame.from_records(records, columns=ISSUE_REPORT_COLUMNS)
