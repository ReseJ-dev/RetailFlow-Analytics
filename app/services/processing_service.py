"""Thin service connecting uploaded datasets to the central processing pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from typing import Protocol

import pandas as pd
from xlsxwriter import Workbook

from app.state import ApplicationStatus, SessionState, StateKey, initialize_state
from retailflow.common.exceptions import DataSourceError, RetailFlowError
from retailflow.ingestion.models import LoadedDataset
from retailflow.models import ProcessingProgress, ProcessingResult, ProcessingStage
from retailflow.pipeline import DataProcessingPipeline
from retailflow.reporting.formatting import (
    configure_print_layout,
    create_report_formats,
    write_dataframe_table,
    write_key_values,
    write_title,
)
from retailflow.transformation.cleaner import DuplicateStrategy
from retailflow.validation import (
    CombinedValidationResult,
    DatasetType,
    DatasetValidationResult,
    ValidationIssue,
    ValidationSeverity,
)

logger = logging.getLogger("retailflow.app.processing")


class ProcessingServiceError(RetailFlowError):
    """Raised when the UI processing orchestration cannot finish safely."""


class QualityIssueCategory(StrEnum):
    """Management-friendly issue categories used by the Data Quality page."""

    MISSING_REQUIRED_COLUMNS = "Missing Required Columns"
    MISSING_VALUES = "Missing Values"
    DUPLICATE_RECORDS = "Duplicate Records"
    INVALID_DATA_TYPES = "Invalid Data Types"
    INVALID_RELATIONSHIPS = "Invalid Relationships"
    BUSINESS_RULE_VIOLATIONS = "Business Rule Violations"
    TRANSFORMATION_WARNINGS = "Transformation Warnings"


@dataclass(frozen=True, slots=True)
class ProcessingProgressEvent:
    """One of seven user-facing processing stages."""

    step: int
    total_steps: int
    label: str

    @property
    def fraction(self) -> float:
        return self.step / self.total_steps


@dataclass(frozen=True, slots=True)
class DataQualitySummary:
    """Transparent aggregate metrics for a processed source collection."""

    source_rows: int
    valid_rows: int
    excluded_rows: int
    warnings: int
    errors: int
    quality_score: float


@dataclass(frozen=True, slots=True)
class IssueGroupSummary:
    """Aggregate presentation details for one issue category."""

    category: QualityIssueCategory
    affected_rows: int
    highest_severity: ValidationSeverity
    explanation: str
    recommended_action: str
    issues: tuple[ValidationIssue, ...]


type ProgressCallback = Callable[[ProcessingProgressEvent], None]


class PipelineProtocol(Protocol):
    """Small injectable subset of the central pipeline used by this service."""

    def process(
        self,
        orders: LoadedDataset,
        products: LoadedDataset,
        inventory: LoadedDataset,
        returns: LoadedDataset,
        targets: LoadedDataset | None = None,
        *,
        column_overrides: Mapping[DatasetType | str, Mapping[str, str]] | None = None,
        progress_callback: Callable[[ProcessingProgress], None] | None = None,
    ) -> ProcessingResult:
        """Process loaded datasets through the central pipeline."""
        ...


type PipelineFactory = Callable[..., PipelineProtocol]

_REQUIRED_DATASETS = (
    DatasetType.ORDERS,
    DatasetType.PRODUCTS,
    DatasetType.INVENTORY,
    DatasetType.RETURNS,
)

_PROGRESS_LABELS = (
    "Reading source data",
    "Applying column mappings",
    "Validating structure",
    "Cleaning and normalizing values",
    "Checking business rules",
    "Merging datasets",
    "Preparing quality summary",
)

_GROUP_CONTENT = {
    QualityIssueCategory.MISSING_REQUIRED_COLUMNS: (
        "Required source fields are missing or cannot be mapped unambiguously.",
        "Return to Upload Data and correct the column mapping or source file.",
    ),
    QualityIssueCategory.MISSING_VALUES: (
        "Required row-level values are empty.",
        "Supply the missing values or exclude the affected rows.",
    ),
    QualityIssueCategory.DUPLICATE_RECORDS: (
        "Multiple records use the same business key.",
        "Review the duplicates and retain only the intended record.",
    ),
    QualityIssueCategory.INVALID_DATA_TYPES: (
        "Values could not be interpreted as the required number, date, or percentage type.",
        "Correct the source format and validate the files again.",
    ),
    QualityIssueCategory.INVALID_RELATIONSHIPS: (
        "References between orders, products, inventory, or returns are inconsistent.",
        "Correct the referenced identifiers or add the missing source records.",
    ),
    QualityIssueCategory.BUSINESS_RULE_VIOLATIONS: (
        "Values violate a RetailFlow business validation rule.",
        "Review the rule message and correct or exclude the affected rows.",
    ),
    QualityIssueCategory.TRANSFORMATION_WARNINGS: (
        "Values were changed or excluded while normalizing source data.",
        "Review the transformation result and explicitly accept valid warnings.",
    ),
}


def _dataset_key(value: object) -> DatasetType | None:
    try:
        if value == "targets":
            return DatasetType.MONTHLY_TARGETS
        return DatasetType(str(value))
    except ValueError:
        return None


def _normalise_datasets(raw: object) -> dict[DatasetType, LoadedDataset]:
    if not isinstance(raw, Mapping):
        raise DataSourceError("Uploaded datasets are not available in this session.")
    datasets: dict[DatasetType, LoadedDataset] = {}
    for key, value in raw.items():
        dataset_type = _dataset_key(key)
        if dataset_type is not None and isinstance(value, LoadedDataset):
            datasets[dataset_type] = value
    missing = [item.value for item in _REQUIRED_DATASETS if item not in datasets]
    if missing:
        raise DataSourceError(
            "Upload all required datasets before starting validation.",
            technical_detail=f"Missing datasets: {', '.join(missing)}",
        )
    return datasets


def _mapping_value(settings: object, key: str, default: object = None) -> object:
    return settings.get(key, default) if isinstance(settings, Mapping) else default


def _pipeline_options(settings: object) -> dict[str, object]:
    return {
        "default_currency": _mapping_value(settings, "default_currency"),
        "exchange_rates": _mapping_value(settings, "exchange_rates"),
        "duplicate_strategy": _mapping_value(
            settings, "duplicate_strategy", DuplicateStrategy.KEEP_FIRST
        ),
        "month_first": bool(_mapping_value(settings, "month_first", False)),
    }


def _normalise_overrides(
    raw: object,
) -> dict[DatasetType | str, Mapping[str, str]]:
    if not isinstance(raw, Mapping):
        return {}
    overrides: dict[DatasetType | str, Mapping[str, str]] = {}
    for key, value in raw.items():
        dataset_type = _dataset_key(key)
        if dataset_type is not None and isinstance(value, Mapping):
            overrides[dataset_type] = {str(source): str(target) for source, target in value.items()}
    return overrides


def _emit(callback: ProgressCallback | None, step: int) -> None:
    if callback is not None:
        callback(ProcessingProgressEvent(step, len(_PROGRESS_LABELS), _PROGRESS_LABELS[step - 1]))


def _pipeline_progress_adapter(
    callback: ProgressCallback | None,
) -> Callable[[ProcessingProgress], None]:
    emitted: set[int] = set()

    def report(progress: ProcessingProgress) -> None:
        stage_steps = {
            ProcessingStage.MAPPING: (2,),
            ProcessingStage.TRANSFORMATION: (3, 4),
            ProcessingStage.VALIDATION: (5,),
            ProcessingStage.MERGING: (6,),
            ProcessingStage.COMPLETE: (7,),
        }[progress.stage]
        for step in stage_steps:
            if step not in emitted:
                _emit(callback, step)
                emitted.add(step)

    return report


def combined_validation_result(result: ProcessingResult) -> CombinedValidationResult:
    """Build the existing combined validation model from pipeline output."""
    dataset_results = tuple(
        DatasetValidationResult(
            dataset_type=dataset_type,
            source_filename=result.source_metadata[dataset_type].filename
            if dataset_type in result.source_metadata
            else None,
            total_rows=statistics.input_rows,
            issues=tuple(
                issue for issue in result.validation_issues if issue.source_dataset is dataset_type
            ),
        )
        for dataset_type, statistics in result.statistics.by_dataset.items()
    )
    return CombinedValidationResult(dataset_results)


def build_quality_summary(result: ProcessingResult) -> DataQualitySummary:
    """Calculate summary counts and reuse the documented rule-based score."""
    validation = combined_validation_result(result)
    return DataQualitySummary(
        source_rows=result.statistics.total_input_rows,
        valid_rows=result.statistics.total_processed_rows,
        excluded_rows=result.statistics.total_excluded_rows,
        warnings=validation.warning_count,
        errors=validation.error_count,
        quality_score=validation.quality_score,
    )


def categorize_issue(issue: ValidationIssue) -> QualityIssueCategory:
    """Map one canonical issue code into a stable management category."""
    code = issue.issue_code.casefold()
    if code in {"missing_required_column", "ambiguous_column_mapping"}:
        return QualityIssueCategory.MISSING_REQUIRED_COLUMNS
    if code.startswith("missing_"):
        return QualityIssueCategory.MISSING_VALUES
    if "duplicate" in code:
        return QualityIssueCategory.DUPLICATE_RECORDS
    if code in {
        "unknown_order_id",
        "unknown_product_id",
        "return_date_before_order_date",
        "returned_quantity_exceeds_sold",
    }:
        return QualityIssueCategory.INVALID_RELATIONSHIPS
    if code in {
        "invalid_date",
        "invalid_month",
        "invalid_numeric_value",
        "invalid_purchase_cost",
        "invalid_quantity",
        "invalid_restock_date",
        "invalid_return_quantity",
        "invalid_unit_price",
        "invalid_vat_rate",
    }:
        return QualityIssueCategory.INVALID_DATA_TYPES
    if issue.severity is ValidationSeverity.WARNING:
        return QualityIssueCategory.TRANSFORMATION_WARNINGS
    return QualityIssueCategory.BUSINESS_RULE_VIOLATIONS


def group_issues(
    issues: tuple[ValidationIssue, ...],
) -> tuple[IssueGroupSummary, ...]:
    """Group issues in the requested stable display order."""
    grouped: dict[QualityIssueCategory, list[ValidationIssue]] = {
        category: [] for category in QualityIssueCategory
    }
    for issue in issues:
        grouped[categorize_issue(issue)].append(issue)
    severity_rank = {
        ValidationSeverity.INFO: 0,
        ValidationSeverity.WARNING: 1,
        ValidationSeverity.ERROR: 2,
    }
    summaries: list[IssueGroupSummary] = []
    for category in QualityIssueCategory:
        category_issues = tuple(grouped[category])
        if not category_issues:
            continue
        affected = {
            (issue.source_dataset, issue.row_number)
            for issue in category_issues
            if issue.row_number is not None
        }
        structural_datasets = {
            issue.source_dataset for issue in category_issues if issue.row_number is None
        }
        highest = max(category_issues, key=lambda item: severity_rank[item.severity]).severity
        explanation, action = _GROUP_CONTENT[category]
        summaries.append(
            IssueGroupSummary(
                category,
                len(affected) + len(structural_datasets),
                highest,
                explanation,
                action,
                category_issues,
            )
        )
    return tuple(summaries)


def has_blocking_structural_errors(result: ProcessingResult) -> bool:
    """Return whether dataset-level structural errors forbid continuation."""
    return any(
        issue.severity is ValidationSeverity.ERROR
        and issue.row_number is None
        and not issue.row_can_continue
        for issue in result.validation_issues
    )


def issue_identifier(issue: ValidationIssue, occurrence: int) -> str:
    """Return a stable-enough session key without exposing issue values."""
    return "|".join(
        (
            issue.source_dataset.value,
            issue.source_filename or "",
            str(issue.row_number or "dataset"),
            issue.field or "",
            issue.issue_code,
            str(occurrence),
        )
    )


def _safe_original_value(issue: ValidationIssue) -> str:
    field = (issue.field or "").casefold()
    if any(token in field for token in ("customer", "email", "token", "secret", "password")):
        return "[REDACTED]"
    value = str(issue.original_value)
    return value if len(value) <= 120 else f"{value[:117]}..."


def issues_dataframe(
    issues: tuple[ValidationIssue, ...], actions: Mapping[str, str] | None = None
) -> pd.DataFrame:
    """Return issue details with safe values and review actions."""
    action_mapping = actions or {}
    records = []
    for occurrence, issue in enumerate(issues):
        identifier = issue_identifier(issue, occurrence)
        records.append(
            {
                "severity": issue.severity.value,
                "source_dataset": issue.source_dataset.value,
                "source_file": issue.source_filename,
                "row_number": issue.row_number,
                "field": issue.field,
                "issue_code": issue.issue_code,
                "issue": issue.message,
                "original_value": _safe_original_value(issue),
                "recommended_action": issue.recommended_action,
                "action_taken": action_mapping.get(identifier, "Pending review"),
            }
        )
    return pd.DataFrame.from_records(records)


def generate_quality_report(
    result: ProcessingResult,
    *,
    actions: Mapping[str, str] | None = None,
    import_settings: Mapping[str, object] | None = None,
) -> bytes:
    """Generate a focused in-memory quality workbook using shared report formats."""
    output = BytesIO()
    workbook = Workbook(output, {"in_memory": True, "nan_inf_to_errors": True})
    formats = create_report_formats(workbook)
    summary = build_quality_summary(result)
    sheet = workbook.add_worksheet("Summary")
    write_title(sheet, "Data Quality Summary", formats)
    final_row = write_key_values(
        sheet,
        [
            ("Source Rows Processed", summary.source_rows),
            ("Valid Rows", summary.valid_rows),
            ("Excluded Rows", summary.excluded_rows),
            ("Warnings", summary.warnings),
            ("Errors", summary.errors),
            ("Rule-based Quality Score", f"{summary.quality_score:.1f}%"),
        ],
        2,
        formats,
    )
    configure_print_layout(
        sheet,
        report_id="data-quality-report",
        generated_at=pd.Timestamp.now().to_pydatetime(),
        last_row=final_row,
        last_column=3,
        landscape=False,
    )
    sheet = workbook.add_worksheet("Detailed Issues")
    issue_frame = issues_dataframe(result.validation_issues, actions)
    write_title(sheet, "Detailed Validation Issues", formats)
    write_dataframe_table(sheet, issue_frame, 2, 0, formats, "QualityIssues", freeze_at=(3, 0))
    include_excluded = bool((import_settings or {}).get("exclude_invalid_rows", True))
    if include_excluded:
        sheet = workbook.add_worksheet("Excluded Rows")
        write_title(sheet, "Excluded Rows", formats)
        write_dataframe_table(
            sheet,
            result.excluded_rows,
            2,
            0,
            formats,
            "QualityExcludedRows",
            freeze_at=(3, 0),
        )
    sheet = workbook.add_worksheet("Configuration")
    write_title(sheet, "Validation Configuration", formats)
    allowed_settings = (
        "default_currency",
        "duplicate_strategy",
        "month_first",
        "exclude_invalid_rows",
        "allow_unknown_products",
    )
    metadata = [
        (key.replace("_", " ").title(), (import_settings or {}).get(key, "Default"))
        for key in allowed_settings
    ]
    write_key_values(sheet, metadata, 2, formats)
    workbook.close()
    return output.getvalue()


def run_processing(
    state: SessionState,
    *,
    progress_callback: ProgressCallback | None = None,
    pipeline_factory: PipelineFactory = DataProcessingPipeline,
) -> ProcessingResult:
    """Retrieve session inputs, execute the central pipeline, and store its result."""
    initialize_state(state)
    current_stage = _PROGRESS_LABELS[0]
    state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.VALIDATING
    try:
        _emit(progress_callback, 1)
        datasets = _normalise_datasets(state[StateKey.LOADED_DATASETS.value])
        overrides = _normalise_overrides(state[StateKey.COLUMN_MAPPINGS.value])
        settings = state[StateKey.IMPORT_SETTINGS.value]
        pipeline = pipeline_factory(**_pipeline_options(settings))

        def track(progress: ProcessingProgress) -> None:
            nonlocal current_stage
            adapter(progress)
            stage_steps = {
                ProcessingStage.MAPPING: 2,
                ProcessingStage.TRANSFORMATION: 4,
                ProcessingStage.VALIDATION: 5,
                ProcessingStage.MERGING: 6,
                ProcessingStage.COMPLETE: 7,
            }
            current_stage = _PROGRESS_LABELS[stage_steps[progress.stage] - 1]
            state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.PROCESSING

        adapter = _pipeline_progress_adapter(progress_callback)
        result = pipeline.process(
            datasets[DatasetType.ORDERS],
            datasets[DatasetType.PRODUCTS],
            datasets[DatasetType.INVENTORY],
            datasets[DatasetType.RETURNS],
            datasets.get(DatasetType.MONTHLY_TARGETS),
            column_overrides=overrides,
            progress_callback=track,
        )
        state[StateKey.PROCESSING_RESULT.value] = result
        state[StateKey.VALIDATION_RESULT.value] = combined_validation_result(result)
        state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.READY
        logger.info(
            "Processing service completed with %d source rows and %d issues",
            result.statistics.total_input_rows,
            len(result.validation_issues),
        )
        return result
    except RetailFlowError:
        state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.FAILED
        logger.exception("Processing failed during stage '%s'", current_stage)
        raise
    except Exception as error:
        state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.FAILED
        logger.exception("Unexpected processing failure during stage '%s'", current_stage)
        raise ProcessingServiceError(
            "RetailFlow could not validate the uploaded datasets.",
            technical_detail=f"Stage: {current_stage}; {error}",
        ) from error


__all__ = [
    "DataQualitySummary",
    "IssueGroupSummary",
    "ProcessingProgressEvent",
    "ProcessingServiceError",
    "QualityIssueCategory",
    "build_quality_summary",
    "categorize_issue",
    "generate_quality_report",
    "group_issues",
    "has_blocking_structural_errors",
    "issue_identifier",
    "issues_dataframe",
    "run_processing",
]
