"""Tests for Streamlit-to-pipeline processing orchestration."""

from io import BytesIO

import openpyxl
import pandas as pd
import pytest
from app.services.processing_service import (
    QualityIssueCategory,
    build_quality_summary,
    categorize_issue,
    generate_quality_report,
    has_blocking_structural_errors,
    run_processing,
)
from app.state import ApplicationStatus, StateKey, initialize_state

from retailflow.common.exceptions import DataSourceError
from retailflow.ingestion.models import FileMetadata, LoadedDataset
from retailflow.validation import DatasetType, ValidationIssue, ValidationSeverity


def _loaded(filename: str, dataframe: pd.DataFrame) -> LoadedDataset:
    return LoadedDataset(
        dataframe=dataframe,
        metadata=FileMetadata(
            filename=filename,
            file_type="csv",
            file_size=100,
            row_count=len(dataframe),
            column_count=len(dataframe.columns),
            columns=tuple(str(column) for column in dataframe.columns),
            detected_delimiter=",",
            detected_encoding="utf-8",
        ),
    )


def _datasets() -> dict[str, LoadedDataset]:
    return {
        "orders": _loaded(
            "orders.csv",
            pd.DataFrame(
                {
                    "order_id": ["O-1"],
                    "order_date": ["2025-01-01"],
                    "product_id": ["P-1"],
                    "quantity": [2],
                    "unit_price": [10.0],
                    "currency": ["EUR"],
                }
            ),
        ),
        "products": _loaded(
            "products.csv",
            pd.DataFrame(
                {
                    "product_id": ["P-1"],
                    "product_name": ["Desk"],
                    "purchase_cost": [5.0],
                    "recommended_price": [10.0],
                }
            ),
        ),
        "inventory": _loaded(
            "inventory.csv",
            pd.DataFrame(
                {
                    "product_id": ["P-1"],
                    "warehouse": ["Nicosia"],
                    "stock_quantity": [10],
                }
            ),
        ),
        "returns": _loaded(
            "returns.csv",
            pd.DataFrame(
                columns=[
                    "return_id",
                    "order_id",
                    "product_id",
                    "return_date",
                    "quantity",
                    "refund_amount",
                ]
            ),
        ),
    }


def _state() -> dict[str, object]:
    state: dict[str, object] = {}
    initialize_state(state)
    state[StateKey.LOADED_DATASETS.value] = _datasets()
    state[StateKey.COLUMN_MAPPINGS.value] = {}
    state[StateKey.IMPORT_SETTINGS.value] = {
        "default_currency": "EUR",
        "duplicate_strategy": "keep_first",
        "exclude_invalid_rows": True,
    }
    return state


def _issue(
    code: str,
    *,
    severity: ValidationSeverity = ValidationSeverity.ERROR,
    row_number: int | None = 2,
) -> ValidationIssue:
    return ValidationIssue(
        severity,
        DatasetType.ORDERS,
        "orders.csv",
        row_number,
        "product_id",
        code,
        "Example issue.",
        "P-X",
        "Correct the value.",
        severity is not ValidationSeverity.ERROR,
    )


def test_run_processing_uses_session_inputs_and_stores_result() -> None:
    state = _state()
    progress = []

    result = run_processing(state, progress_callback=progress.append)

    assert state[StateKey.PROCESSING_RESULT.value] is result
    assert state[StateKey.VALIDATION_RESULT.value] is not None
    assert state[StateKey.APPLICATION_STATUS.value] is ApplicationStatus.READY
    assert [event.step for event in progress] == list(range(1, 8))
    assert [event.label for event in progress] == [
        "Reading source data",
        "Applying column mappings",
        "Validating structure",
        "Cleaning and normalizing values",
        "Checking business rules",
        "Merging datasets",
        "Preparing quality summary",
    ]
    summary = build_quality_summary(result)
    assert summary.source_rows == 3
    assert summary.valid_rows == 3
    assert summary.excluded_rows == 0
    assert summary.quality_score == 100.0


def test_run_processing_rejects_missing_required_dataset() -> None:
    state = _state()
    loaded = state[StateKey.LOADED_DATASETS.value]
    assert isinstance(loaded, dict)
    loaded.pop("products")

    with pytest.raises(DataSourceError, match="Upload all required datasets"):
        run_processing(state)

    assert state[StateKey.APPLICATION_STATUS.value] is ApplicationStatus.FAILED


@pytest.mark.parametrize(
    ("issue", "expected"),
    [
        (
            _issue("missing_required_column", row_number=None),
            QualityIssueCategory.MISSING_REQUIRED_COLUMNS,
        ),
        (_issue("missing_product_id"), QualityIssueCategory.MISSING_VALUES),
        (_issue("duplicated_order_row"), QualityIssueCategory.DUPLICATE_RECORDS),
        (_issue("invalid_unit_price"), QualityIssueCategory.INVALID_DATA_TYPES),
        (_issue("unknown_product_id"), QualityIssueCategory.INVALID_RELATIONSHIPS),
        (_issue("negative_stock"), QualityIssueCategory.BUSINESS_RULE_VIOLATIONS),
        (
            _issue("normalized_value", severity=ValidationSeverity.WARNING),
            QualityIssueCategory.TRANSFORMATION_WARNINGS,
        ),
    ],
)
def test_categorize_issue_covers_every_display_group(
    issue: ValidationIssue, expected: QualityIssueCategory
) -> None:
    assert categorize_issue(issue) is expected


def test_structural_errors_block_continuation() -> None:
    state = _state()
    loaded = state[StateKey.LOADED_DATASETS.value]
    assert isinstance(loaded, dict)
    orders = loaded["orders"]
    loaded["orders"] = _loaded("orders.csv", orders.dataframe.drop(columns=["order_id"]))

    result = run_processing(state)

    assert has_blocking_structural_errors(result)


def test_quality_report_contains_required_worksheets() -> None:
    state = _state()
    result = run_processing(state)

    report = generate_quality_report(
        result,
        import_settings={"exclude_invalid_rows": True, "default_currency": "EUR"},
    )

    workbook = openpyxl.load_workbook(BytesIO(report))
    assert workbook.sheetnames == [
        "Summary",
        "Detailed Issues",
        "Excluded Rows",
        "Configuration",
    ]
    assert workbook["Summary"]["B3"].value == 3
    assert len(report) > 1_000
