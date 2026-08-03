"""Data validation interfaces for RetailFlow Analytics."""

from retailflow.validation.data_validator import DataValidator, export_issues_dataframe
from retailflow.validation.schemas import DatasetSchema, DatasetType, get_dataset_schema
from retailflow.validation.validation_result import (
    CombinedValidationResult,
    DatasetValidationResult,
    ValidationIssue,
    ValidationSeverity,
    issues_to_dataframe,
)

__all__ = [
    "CombinedValidationResult",
    "DataValidator",
    "DatasetSchema",
    "DatasetType",
    "DatasetValidationResult",
    "ValidationIssue",
    "ValidationSeverity",
    "export_issues_dataframe",
    "get_dataset_schema",
    "issues_to_dataframe",
]
