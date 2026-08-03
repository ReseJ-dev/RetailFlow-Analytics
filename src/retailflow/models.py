"""Shared models returned by the central processing pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

import pandas as pd

from retailflow.ingestion.models import FileMetadata
from retailflow.validation import DatasetType, ValidationIssue


class ProcessingStage(StrEnum):
    """Stable progress stages for CLI and UI integrations."""

    MAPPING = "mapping"
    TRANSFORMATION = "transformation"
    VALIDATION = "validation"
    MERGING = "merging"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class ProcessingProgress:
    """One progress update emitted without exposing source records."""

    stage: ProcessingStage
    completed_steps: int
    total_steps: int
    message: str

    @property
    def fraction(self) -> float:
        return self.completed_steps / self.total_steps if self.total_steps else 1.0


@dataclass(frozen=True, slots=True)
class DatasetProcessingStatistics:
    """Counts for one source dataset."""

    input_rows: int
    processed_rows: int
    excluded_rows: int
    issue_count: int


@dataclass(frozen=True, slots=True)
class ProcessingStatistics:
    """Aggregate and per-dataset processing counts."""

    by_dataset: Mapping[DatasetType, DatasetProcessingStatistics] = field(default_factory=dict)

    @property
    def total_input_rows(self) -> int:
        return sum(item.input_rows for item in self.by_dataset.values())

    @property
    def total_processed_rows(self) -> int:
        return sum(item.processed_rows for item in self.by_dataset.values())

    @property
    def total_excluded_rows(self) -> int:
        return sum(item.excluded_rows for item in self.by_dataset.values())

    @property
    def total_issues(self) -> int:
        return sum(item.issue_count for item in self.by_dataset.values())


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    """Complete output of one RetailFlow processing run."""

    processed_orders: pd.DataFrame
    products: pd.DataFrame
    inventory: pd.DataFrame
    returns: pd.DataFrame
    targets: pd.DataFrame
    excluded_rows: pd.DataFrame
    validation_issues: tuple[ValidationIssue, ...]
    statistics: ProcessingStatistics
    source_metadata: Mapping[DatasetType, FileMetadata]

    @property
    def orders(self) -> pd.DataFrame:
        """Compatibility alias for order-level processed data."""
        return self.processed_orders

    @property
    def issues(self) -> tuple[ValidationIssue, ...]:
        return self.validation_issues
