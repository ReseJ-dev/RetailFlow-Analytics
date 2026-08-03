"""Unit tests for cleaning, normalization, and duplicate policies."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from retailflow.transformation import (
    CurrencyConverter,
    DataCleaner,
    DuplicateStrategy,
    UnsupportedCurrencyError,
    normalize_country,
    normalize_currency,
    normalize_identifier,
    normalize_order_status,
    normalize_sales_channel,
    normalize_string,
    parse_date,
    parse_integer,
    parse_number,
)
from retailflow.validation import (
    DatasetType,
    DatasetValidationResult,
    ValidationIssue,
    ValidationSeverity,
)


def order_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": [" O-1 ", "O-2"],
            "order_date": ["31/01/2025", 45689],
            "product_id": [" P-1 ", "P-2"],
            "quantity": ["2", "3"],
            "unit_price": ["1.234,50", "10.25"],
            "discount": ["15%", "0,25"],
            "currency": [" eur ", "USD"],
            "country": [" uk ", "USA"],
            "order_status": [" PAID ", "in_progress"],
            "sales_channel": [" Online ", "store"],
        }
    )


def duplicate_products() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "product_id": ["P-1", "P-1", "P-2"],
            "product_name": ["Old", "New", "Unique"],
            "purchase_cost": [1, 2, 3],
            "recommended_price": [2, 3, 4],
        }
    )


def test_string_normalizers_preserve_identifiers_and_canonicalize_values() -> None:
    assert normalize_identifier("  AB-12  ") == "AB-12"
    assert pd.isna(normalize_string("  "))
    assert normalize_country("great britain") == "United Kingdom"
    assert normalize_currency(" eur ") == "EUR"
    assert normalize_order_status("CANCELED") == "cancelled"
    assert normalize_sales_channel("e-commerce") == "website"


def test_numeric_and_date_parsers_cover_supported_formats() -> None:
    assert parse_number("1.234,56") == 1234.56
    assert parse_number("1,234.56") == 1234.56
    assert parse_number("12.5%") == 0.125
    assert parse_integer("12") == 12
    assert parse_integer("12.5") is None
    assert parse_date("31/01/2025") == pd.Timestamp("2025-01-31")
    assert parse_date("01/31/2025", month_first=True) == pd.Timestamp("2025-01-31")
    assert parse_date(45689) == pd.Timestamp("2025-02-01")
    assert parse_date("not-a-date") is None


def test_cleaner_normalizes_values_and_converts_currency() -> None:
    result = DataCleaner(default_currency="USD", exchange_rates={"EUR": 1.1}).clean_orders(
        order_rows()
    )

    clean = result.cleaned_dataframe
    assert clean["order_id"].tolist() == ["O-1", "O-2"]
    assert clean["product_id"].tolist() == ["P-1", "P-2"]
    assert clean["country"].tolist() == ["United Kingdom", "United States"]
    assert clean["currency"].tolist() == ["USD", "USD"]
    assert clean["unit_price"].tolist() == pytest.approx([1357.95, 10.25])
    assert clean["discount"].tolist() == pytest.approx([0.15, 0.25])
    assert clean["order_status"].tolist() == ["completed", "pending"]
    assert clean["sales_channel"].tolist() == ["website", "retail"]
    assert clean["order_date"].tolist() == [
        pd.Timestamp("2025-01-31"),
        pd.Timestamp("2025-02-01"),
    ]
    assert result.statistics.changed_values > 0
    assert result.excluded_rows.empty


@pytest.mark.parametrize(
    ("strategy", "expected_names", "excluded"),
    [
        (DuplicateStrategy.KEEP_FIRST, ["Old", "Unique"], 1),
        (DuplicateStrategy.KEEP_LATEST, ["New", "Unique"], 1),
        (DuplicateStrategy.EXCLUDE_ALL, ["Unique"], 2),
        (DuplicateStrategy.ERROR, ["Unique"], 2),
    ],
)
def test_all_duplicate_strategies(
    strategy: DuplicateStrategy, expected_names: list[str], excluded: int
) -> None:
    result = DataCleaner(duplicate_strategy=strategy).clean(
        DatasetType.PRODUCTS, duplicate_products()
    )

    assert result.cleaned_dataframe["product_name"].tolist() == expected_names
    assert len(result.excluded_rows) == excluded
    assert result.statistics.duplicate_rows == excluded
    severities = {issue.severity for issue in result.issues}
    expected = (
        ValidationSeverity.ERROR
        if strategy is DuplicateStrategy.ERROR
        else ValidationSeverity.WARNING
    )
    assert severities == {expected}


def test_keep_latest_uses_dataset_date_not_input_order() -> None:
    frame = pd.DataFrame(
        {
            "order_id": ["O-1", "O-1", "O-2"],
            "order_date": ["2025-03-01", "2025-01-01", "2025-02-01"],
            "product_id": ["P-1", "P-1", "P-2"],
            "quantity": [3, 1, 2],
            "unit_price": [30, 10, 20],
        }
    )

    result = DataCleaner(duplicate_strategy="keep_latest").clean_orders(frame)

    assert result.cleaned_dataframe["quantity"].tolist() == [3, 2]


def test_invalid_values_and_unsupported_currency_are_excluded_and_reported() -> None:
    frame = order_rows().iloc[:1].copy()
    frame.loc[0, "quantity"] = "many"
    frame.loc[0, "currency"] = "XYZ"

    result = DataCleaner().clean(DatasetType.ORDERS, frame)

    assert result.cleaned_dataframe.empty
    assert len(result.excluded_rows) == 1
    assert {issue.issue_code for issue in result.issues} == {
        "invalid_numeric_value",
        "unsupported_currency",
    }
    assert result.statistics.invalid_values == 2


def test_blocking_validation_rows_are_excluded_but_warnings_continue() -> None:
    frame = order_rows()
    validation = DatasetValidationResult(
        DatasetType.ORDERS,
        "orders.csv",
        len(frame),
        (
            ValidationIssue(
                ValidationSeverity.ERROR,
                DatasetType.ORDERS,
                "orders.csv",
                2,
                "order_id",
                "blocked",
                "blocked",
                "O-1",
                "Fix the row.",
                False,
            ),
            ValidationIssue(
                ValidationSeverity.WARNING,
                DatasetType.ORDERS,
                "orders.csv",
                3,
                "discount",
                "warning",
                "Review this value.",
                "0,25",
                "Review the row.",
                True,
            ),
        ),
    )

    result = DataCleaner(exchange_rates={"EUR": 1.1}).clean(
        DatasetType.ORDERS, frame, validation_result=validation
    )

    assert result.cleaned_dataframe["order_id"].tolist() == ["O-2"]
    assert result.excluded_rows["order_id"].tolist() == [" O-1 "]
    assert len(result.issues) == 2


def test_currency_converter_is_injected_and_never_calls_external_services() -> None:
    converter = CurrencyConverter("EUR", {"USD": 0.9})

    assert converter.convert(10, "usd") == 9
    assert converter.convert(10, "EUR") == 10
    with pytest.raises(UnsupportedCurrencyError):
        converter.convert(10, "GBP")


def test_invalid_date_is_excluded_and_reported() -> None:
    frame = order_rows().iloc[:1].copy()
    frame.loc[0, "order_date"] = "yesterday-ish"

    result = DataCleaner(exchange_rates={"EUR": 1.1}).clean(DatasetType.ORDERS, frame)

    assert result.cleaned_dataframe.empty
    assert result.issues[0].issue_code == "invalid_date"


def test_normalizer_accepts_native_datetime() -> None:
    assert parse_date(datetime(2025, 3, 4, 15, 30)) == pd.Timestamp("2025-03-04")
