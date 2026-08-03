"""Unit tests for dataset validation, business rules, and quality reporting."""

from __future__ import annotations

import pandas as pd

from retailflow.ingestion.models import FileMetadata, LoadedDataset
from retailflow.validation import (
    CombinedValidationResult,
    DatasetType,
    DatasetValidationResult,
    DataValidator,
    ValidationIssue,
    ValidationSeverity,
    export_issues_dataframe,
)


def valid_orders() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": ["O-1", "O-2"],
            "order_date": ["2025-01-10", "2025-02-01"],
            "product_id": ["P-1", "P-2"],
            "quantity": [2, 1],
            "unit_price": [10.0, 20.0],
            "discount": [0.1, 0.0],
            "currency": ["EUR", "USD"],
        }
    )


def valid_products() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "product_id": ["P-1", "P-2"],
            "product_name": ["Desk", "Chair"],
            "purchase_cost": [5.0, 10.0],
            "recommended_price": [10.0, 20.0],
            "vat_rate": [0.19, 0.2],
        }
    )


def issue_codes(result: DatasetValidationResult) -> set[str]:
    return {issue.issue_code for issue in result.issues}


def test_valid_combined_data_scores_one_hundred() -> None:
    datasets = {
        DatasetType.ORDERS: valid_orders(),
        DatasetType.PRODUCTS: valid_products(),
        DatasetType.INVENTORY: pd.DataFrame(
            {
                "product_id": ["P-1"],
                "warehouse": ["Nicosia"],
                "stock_quantity": [10],
                "reserved_quantity": [2],
                "reorder_level": [3],
                "last_restock_date": ["2025-01-01"],
            }
        ),
        DatasetType.RETURNS: pd.DataFrame(
            {
                "return_id": ["R-1"],
                "order_id": ["O-1"],
                "product_id": ["P-1"],
                "return_date": ["2025-01-11"],
                "quantity": [1],
                "refund_amount": [9.0],
            }
        ),
        "targets": pd.DataFrame(
            {
                "month": ["2025-01"],
                "revenue_target": [1000],
                "profit_target": [200],
                "orders_target": [20],
            }
        ),
    }

    result = DataValidator().validate_all(datasets)

    assert result.issues == ()
    assert result.quality_score == 100.0
    assert result.can_continue
    assert result.result_for(DatasetType.RETURNS) is not None


def test_orders_report_required_values_numbers_currency_and_duplicates() -> None:
    frame = pd.DataFrame(
        [
            {
                "order_id": None,
                "order_date": None,
                "product_id": "",
                "quantity": "two",
                "unit_price": "ten",
                "discount": 1.5,
                "currency": "XYZ",
            },
            {
                "order_id": "O-2",
                "order_date": "2025-01-01",
                "product_id": "P-1",
                "quantity": 0,
                "unit_price": -1,
                "discount": 0,
                "currency": "EUR",
            },
            {
                "order_id": "O-3",
                "order_date": "2025-01-01",
                "product_id": "P-1",
                "quantity": 1,
                "unit_price": 1,
                "discount": 0,
                "currency": "EUR",
            },
            {
                "order_id": "O-3",
                "order_date": "2025-01-01",
                "product_id": "P-1",
                "quantity": 1,
                "unit_price": 1,
                "discount": 0,
                "currency": "EUR",
            },
        ]
    )

    result = DataValidator().validate_orders(frame, source_filename="orders.csv")

    assert {
        "missing_order_id",
        "missing_order_date",
        "missing_product_id",
        "invalid_quantity",
        "quantity_not_positive",
        "invalid_unit_price",
        "negative_unit_price",
        "discount_out_of_range",
        "unsupported_currency",
        "duplicated_order_row",
    } <= issue_codes(result)
    assert all(issue.source_filename == "orders.csv" for issue in result.issues)
    assert min(issue.row_number for issue in result.issues if issue.row_number) == 2


def test_missing_required_columns_are_dataset_level_blockers() -> None:
    result = DataValidator().validate_orders(pd.DataFrame({"order_id": ["O-1"]}))

    missing = [issue for issue in result.issues if issue.issue_code == "missing_required_column"]
    assert {issue.field for issue in missing} == {
        "order_date",
        "product_id",
        "quantity",
        "unit_price",
    }
    assert all(issue.row_number is None and not issue.row_can_continue for issue in missing)
    assert result.quality_score == 0.0


def test_products_report_all_catalogue_rules() -> None:
    products = pd.DataFrame(
        {
            "product_id": ["P-1", "P-1", "P-3", "P-4"],
            "product_name": ["Desk", None, "Lamp", "Shelf"],
            "purchase_cost": [10, "bad", -1, 20],
            "recommended_price": [5, 20, 3, 30],
            "vat_rate": [0.2, 1.2, 0.1, "bad"],
        }
    )

    result = DataValidator().validate_products(products)

    assert {
        "duplicated_product_id",
        "missing_product_name",
        "invalid_purchase_cost",
        "negative_purchase_cost",
        "recommended_price_below_cost",
        "invalid_vat_rate",
    } <= issue_codes(result)
    warning = next(
        issue for issue in result.issues if issue.issue_code == "recommended_price_below_cost"
    )
    assert warning.severity is ValidationSeverity.WARNING
    assert warning.row_can_continue


def test_inventory_reports_references_quantities_and_date() -> None:
    inventory = pd.DataFrame(
        {
            "product_id": ["P-X"],
            "warehouse": ["Nicosia"],
            "stock_quantity": [-1],
            "reserved_quantity": [2],
            "reorder_level": [-3],
            "last_restock_date": ["not-a-date"],
        }
    )

    result = DataValidator().validate_inventory(inventory, products=valid_products())

    assert {
        "unknown_product_id",
        "negative_stock",
        "reserved_quantity_exceeds_stock",
        "negative_reorder_level",
        "invalid_restock_date",
    } <= issue_codes(result)

    negative_reserved = inventory.copy()
    negative_reserved["product_id"] = "P-1"
    negative_reserved["stock_quantity"] = 1
    negative_reserved["reserved_quantity"] = -1
    assert "negative_reserved_quantity" in issue_codes(
        DataValidator().validate_inventory(negative_reserved, products=valid_products())
    )


def test_returns_report_reference_date_quantity_and_refund_rules() -> None:
    returns = pd.DataFrame(
        {
            "return_id": ["R-1", "R-2"],
            "order_id": ["O-1", "O-X"],
            "product_id": ["P-1", "P-X"],
            "return_date": ["2025-01-01", "2025-01-01"],
            "quantity": [3, "bad"],
            "refund_amount": [-1, 2],
        }
    )

    result = DataValidator().validate_returns(
        returns,
        orders=valid_orders(),
        products=valid_products(),
    )

    assert {
        "unknown_order_id",
        "unknown_product_id",
        "invalid_return_quantity",
        "negative_refund_amount",
        "return_date_before_order_date",
        "returned_quantity_exceeds_sold",
    } <= issue_codes(result)


def test_targets_report_invalid_negative_and_duplicate_months() -> None:
    targets = pd.DataFrame(
        {
            "month": ["2025-13", "2025-02", "2025-02"],
            "revenue_target": [-1, 100, 100],
            "profit_target": [1, -2, 20],
            "orders_target": [1, 2, -3],
        }
    )

    result = DataValidator().validate_targets(targets)

    assert {"invalid_month", "negative_target", "duplicate_target_month"} <= issue_codes(result)
    assert sum(issue.issue_code == "duplicate_target_month" for issue in result.issues) == 2


def test_quality_formula_counts_rows_once_and_is_documented_by_example() -> None:
    # Four rows: two clean (2 points), one warning-only (0.5), one error (0).
    # Score = (2 + 0.5 + 0) / 4 * 100 = 62.5.
    warning = ValidationIssue(
        ValidationSeverity.WARNING,
        DatasetType.PRODUCTS,
        None,
        3,
        "recommended_price",
        "warning",
        "Warning",
        5,
        "Review it.",
        True,
    )
    error = ValidationIssue(
        ValidationSeverity.ERROR,
        DatasetType.PRODUCTS,
        None,
        4,
        "product_name",
        "error",
        "Error",
        None,
        "Fix it.",
        False,
    )
    second_error_on_same_row = ValidationIssue(
        ValidationSeverity.ERROR,
        DatasetType.PRODUCTS,
        None,
        4,
        "purchase_cost",
        "another_error",
        "Another error",
        -1,
        "Fix it.",
        False,
    )
    result = DatasetValidationResult(
        DatasetType.PRODUCTS,
        None,
        4,
        (warning, error, second_error_on_same_row),
    )

    assert result.valid_row_count == 2
    assert result.warning_row_count == 1
    assert result.error_row_count == 1
    assert result.quality_score == 62.5


def test_issue_export_is_flat_and_excel_ready() -> None:
    result = DataValidator().validate_orders(
        pd.DataFrame(
            {
                "order_id": [None],
                "order_date": ["2025-01-01"],
                "product_id": ["P-1"],
                "quantity": [1],
                "unit_price": [10],
            }
        ),
        source_filename="orders.xlsx",
    )

    report = export_issues_dataframe(result)

    assert list(report.columns) == [
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
    ]
    assert report.loc[0, "source_filename"] == "orders.xlsx"
    assert report.loc[0, "source_dataset"] == "orders"
    assert report.loc[0, "row_number"] == 2


def test_loaded_dataset_filename_is_propagated() -> None:
    frame = valid_orders()
    loaded = LoadedDataset(
        dataframe=frame,
        metadata=FileMetadata(
            filename="uploaded.csv",
            file_type="csv",
            file_size=100,
            row_count=len(frame),
            column_count=len(frame.columns),
            columns=tuple(frame.columns),
        ),
    )

    result = DataValidator().validate_orders(loaded)

    assert result.source_filename == "uploaded.csv"
    assert result.quality_score == 100.0


def test_combined_score_is_weighted_by_dataset_rows() -> None:
    clean = DatasetValidationResult(DatasetType.ORDERS, None, 3)
    invalid = DatasetValidationResult(
        DatasetType.PRODUCTS,
        None,
        1,
        (
            ValidationIssue(
                ValidationSeverity.ERROR,
                DatasetType.PRODUCTS,
                None,
                2,
                "product_name",
                "missing",
                "Missing",
                None,
                "Provide it.",
                False,
            ),
        ),
    )

    combined = CombinedValidationResult((clean, invalid))

    assert combined.quality_score == 75.0
    assert combined.error_count == 1
    assert not combined.can_continue
