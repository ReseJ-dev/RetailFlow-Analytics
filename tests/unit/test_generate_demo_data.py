"""Tests for the synthetic demonstration-data generator."""

from pathlib import Path

import pandas as pd
import pytest
from scripts.generate_demo_data import generate_demo_data

EXPECTED_FILES = {
    "orders.csv",
    "products.xlsx",
    "inventory.csv",
    "returns.xlsx",
    "monthly_targets.csv",
}

EXPECTED_COLUMNS = {
    "orders.csv": {
        "order_id",
        "order_date",
        "customer_id",
        "product_id",
        "quantity",
        "unit_price",
        "discount",
        "currency",
        "country",
        "sales_channel",
        "order_status",
    },
    "products.xlsx": {
        "product_id",
        "product_name",
        "category",
        "supplier",
        "purchase_cost",
        "recommended_price",
        "vat_rate",
    },
    "inventory.csv": {
        "product_id",
        "warehouse",
        "stock_quantity",
        "reserved_quantity",
        "reorder_level",
        "last_restock_date",
    },
    "returns.xlsx": {
        "return_id",
        "order_id",
        "product_id",
        "return_date",
        "quantity",
        "return_reason",
        "refund_amount",
    },
    "monthly_targets.csv": {"month", "revenue_target", "profit_target", "orders_target"},
}


def _load_generated_files(output_directory: Path) -> dict[str, pd.DataFrame]:
    """Read every generated dataset using its configured file format."""
    return {
        "orders.csv": pd.read_csv(output_directory / "orders.csv"),
        "products.xlsx": pd.read_excel(output_directory / "products.xlsx"),
        "inventory.csv": pd.read_csv(output_directory / "inventory.csv"),
        "returns.xlsx": pd.read_excel(output_directory / "returns.xlsx"),
        "monthly_targets.csv": pd.read_csv(output_directory / "monthly_targets.csv"),
    }


@pytest.fixture
def generated_data(tmp_path: Path) -> dict[str, pd.DataFrame]:
    """Generate a compact invalid dataset for structural tests."""
    generate_demo_data(tmp_path, 120, 24, 1234, include_invalid_rows=True)
    return _load_generated_files(tmp_path)


def test_all_expected_files_are_generated(
    tmp_path: Path, generated_data: dict[str, pd.DataFrame]
) -> None:
    """A generation run should create exactly the five required data files."""
    del generated_data
    generated_names = {path.name for path in tmp_path.iterdir() if path.is_file()}
    assert generated_names == EXPECTED_FILES


def test_required_columns_exist(generated_data: dict[str, pd.DataFrame]) -> None:
    """Each generated dataset should expose its documented schema."""
    for filename, required_columns in EXPECTED_COLUMNS.items():
        assert set(generated_data[filename].columns) == required_columns


def test_ids_mostly_preserve_valid_relationships(
    generated_data: dict[str, pd.DataFrame],
) -> None:
    """All relationships except controlled invalid examples should resolve."""
    orders = generated_data["orders.csv"]
    products = generated_data["products.xlsx"]
    inventory = generated_data["inventory.csv"]
    returns = generated_data["returns.xlsx"]

    valid_product_ids = set(products["product_id"])
    valid_order_ids = set(orders["order_id"])
    assert (~orders["product_id"].isin(valid_product_ids)).sum() == 1
    assert inventory["product_id"].isin(valid_product_ids).all()
    assert (~returns["order_id"].isin(valid_order_ids)).sum() == 1
    assert (set(products["product_id"]) - set(orders["product_id"]))


def test_intentionally_invalid_records_are_present(
    generated_data: dict[str, pd.DataFrame],
) -> None:
    """Every requested quality problem should be present when enabled."""
    orders = generated_data["orders.csv"]
    products = generated_data["products.xlsx"]
    inventory = generated_data["inventory.csv"]
    returns = generated_data["returns.xlsx"]

    assert orders["order_id"].duplicated().any()
    assert (orders["product_id"] == "P_UNKNOWN").any()
    assert (orders["quantity"] < 0).any()
    assert orders["order_date"].isna().any()
    assert (orders["currency"] == "XYZ").any()
    assert pd.to_numeric(orders["unit_price"], errors="coerce").isna().any()
    assert (returns["order_id"] == "O_MISSING").any()
    assert products["product_name"].isna().any()
    assert (inventory["reserved_quantity"] > inventory["stock_quantity"]).any()


def test_invalid_records_are_omitted_when_disabled(tmp_path: Path) -> None:
    """A clean generation run should preserve all core relationships and constraints."""
    generate_demo_data(tmp_path, 80, 20, 5678, include_invalid_rows=False)
    data = _load_generated_files(tmp_path)
    orders = data["orders.csv"]
    products = data["products.xlsx"]
    inventory = data["inventory.csv"]
    returns = data["returns.xlsx"]

    assert len(orders) == 80
    assert not orders["order_id"].duplicated().any()
    assert orders["product_id"].isin(products["product_id"]).all()
    assert (orders["quantity"] > 0).all()
    assert orders["order_date"].notna().all()
    assert products["product_name"].notna().all()
    assert (inventory["reserved_quantity"] <= inventory["stock_quantity"]).all()
    assert returns["order_id"].isin(orders["order_id"]).all()


def test_generation_is_deterministic_for_same_seed(tmp_path: Path) -> None:
    """The same options and seed should produce identical tabular content."""
    first_directory = tmp_path / "first"
    second_directory = tmp_path / "second"
    generate_demo_data(first_directory, 80, 20, 9876, include_invalid_rows=True)
    generate_demo_data(second_directory, 80, 20, 9876, include_invalid_rows=True)

    first_data = _load_generated_files(first_directory)
    second_data = _load_generated_files(second_directory)
    for filename in EXPECTED_FILES:
        pd.testing.assert_frame_equal(first_data[filename], second_data[filename])
