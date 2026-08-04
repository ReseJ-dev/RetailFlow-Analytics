"""Tests for dataset schemas and source-column mapping."""

from retailflow.ingestion.column_mapper import map_columns, normalize_column_name

ORDER_REQUIRED_COLUMNS = ["order_id", "order_date", "product_id", "quantity", "unit_price"]


def test_exact_column_names_match_required_schema() -> None:
    """Canonical source names should map without alias configuration changes."""
    result = map_columns(ORDER_REQUIRED_COLUMNS, "orders")

    assert result.matched_required_columns == {
        column: column for column in ORDER_REQUIRED_COLUMNS
    }
    assert result.missing_required_columns == ()
    assert result.unknown_source_columns == ()
    assert result.ambiguous_matches == {}
    assert result.is_complete


def test_common_aliases_are_matched() -> None:
    """Configured business aliases should map to canonical fields."""
    result = map_columns(
        ["Order Number", "Date", "SKU", "Qty", "Price", "Unexpected Note"],
        "orders",
    )

    assert result.matched_required_columns == {
        "order_id": "Order Number",
        "order_date": "Date",
        "product_id": "SKU",
        "quantity": "Qty",
        "unit_price": "Price",
    }
    assert result.unknown_source_columns == ("Unexpected Note",)


def test_mixed_casing_is_normalized() -> None:
    """Alias matching should be case-insensitive."""
    result = map_columns(
        ["ORDER ID", "order DATE", "Product ID", "QUANTITY", "Unit Price"],
        "orders",
    )

    assert result.missing_required_columns == ()
    assert result.is_complete


def test_whitespace_hyphens_and_duplicate_underscores_are_normalized() -> None:
    """Normalization should produce stable snake-case column names."""
    assert normalize_column_name("  Product---  Code  ") == "product_code"
    assert normalize_column_name("order___date") == "order_date"

    result = map_columns(
        [" order id ", "order-date", " product  id", " qty ", " unit__price "],
        "orders",
    )
    assert result.missing_required_columns == ()


def test_manual_override_maps_custom_column() -> None:
    """A manual source-to-target override should take precedence over aliases."""
    columns = ["Reference", "Date", "SKU", "Qty", "Price"]

    result = map_columns(columns, "orders", manual_overrides={"Reference": "order_id"})

    assert result.matched_required_columns["order_id"] == "Reference"
    assert result.is_complete
    assert result.column_mapping["Reference"] == "order_id"


def test_missing_required_columns_are_reported() -> None:
    """Absent canonical requirements should remain visible to the UI."""
    result = map_columns(["Order Number", "Date", "Notes"], "orders")

    assert result.missing_required_columns == ("product_id", "quantity", "unit_price")
    assert result.unknown_source_columns == ("Notes",)
    assert not result.is_complete


def test_ambiguous_aliases_are_not_silently_selected() -> None:
    """Two aliases for one field should be reported rather than resolved by order."""
    columns = ["Order Number", "Order Reference", "Date", "SKU", "Qty", "Price"]

    result = map_columns(columns, "orders")

    assert result.ambiguous_matches["order_id"] == ("Order Number", "Order Reference")
    assert "order_id" in result.missing_required_columns
    assert "order_id" not in result.matched_required_columns


def test_manual_override_resolves_automatic_ambiguity() -> None:
    """Selecting one source manually should resolve competing automatic aliases."""
    columns = ["Order Number", "Order Reference", "Date", "SKU", "Qty", "Price"]

    result = map_columns(
        columns,
        "orders",
        manual_overrides={"Order Reference": "order_id"},
    )

    assert result.matched_required_columns["order_id"] == "Order Reference"
    assert "order_id" not in result.ambiguous_matches
    assert result.unknown_source_columns == ("Order Number",)


def test_two_manual_source_columns_cannot_map_to_one_target_silently() -> None:
    """Duplicate manual targets should remain ambiguous until the user chooses one."""
    columns = ["Reference A", "Reference B", "Date", "SKU", "Qty", "Price"]

    result = map_columns(
        columns,
        "orders",
        manual_overrides={
            "Reference A": "order_id",
            "Reference B": "order_id",
        },
    )

    assert result.ambiguous_matches["order_id"] == ("Reference A", "Reference B")
    assert "order_id" in result.missing_required_columns
    assert "Reference A" not in result.column_mapping
    assert "Reference B" not in result.column_mapping
