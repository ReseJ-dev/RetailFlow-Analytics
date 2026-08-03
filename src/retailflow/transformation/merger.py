"""Cardinality-safe joins for canonical RetailFlow datasets."""

from __future__ import annotations

import pandas as pd
from pandas.errors import MergeError

from retailflow.common.exceptions import DataValidationError

TRACE_COLUMNS = frozenset(
    {"source_file", "source_row_number", "processing_status", "exclusion_reason"}
)


def _dimension_columns(
    frame: pd.DataFrame, keys: tuple[str, ...], *, prefix: str | None = None
) -> pd.DataFrame:
    selected = [column for column in frame if column not in TRACE_COLUMNS]
    dimension = frame[selected].copy()
    if prefix is not None:
        dimension = dimension.rename(
            columns={column: f"{prefix}{column}" for column in dimension if column not in keys}
        )
    return dimension


def safe_many_to_one_merge(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    on: str | list[str],
    right_name: str,
) -> pd.DataFrame:
    """Left-join a dimension and reject duplicate keys or row multiplication."""
    keys = [on] if isinstance(on, str) else on
    missing = [column for column in keys if column not in left or column not in right]
    if missing:
        raise DataValidationError(
            f"Cannot merge '{right_name}'; join columns are missing.",
            technical_detail=f"Missing join columns: {missing}",
        )
    duplicate_keys = right.duplicated(keys, keep=False)
    if duplicate_keys.any():
        raise DataValidationError(
            f"Cannot merge '{right_name}'; its join keys are not unique.",
            technical_detail=(f"Duplicate key rows: {int(duplicate_keys.sum())}; keys: {keys}"),
        )
    try:
        merged = left.merge(right, how="left", on=keys, validate="many_to_one")
    except MergeError as error:
        raise DataValidationError(
            f"Cannot safely merge '{right_name}'.", technical_detail=str(error)
        ) from error
    if len(merged) != len(left):
        raise DataValidationError(
            f"Merging '{right_name}' changed the fact-table row count.",
            technical_detail=f"Before: {len(left)}; after: {len(merged)}",
        )
    return merged


def merge_orders_with_products(orders: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    products_dimension = _dimension_columns(products, ("product_id",))
    return safe_many_to_one_merge(
        orders, products_dimension, on="product_id", right_name="products"
    )


def merge_orders_with_targets(orders: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    result = orders.copy()
    result["reporting_month"] = pd.to_datetime(result["order_date"]).dt.strftime("%Y-%m")
    if targets.empty:
        return result
    target_dimension = _dimension_columns(targets, ("month",), prefix="target_")
    target_dimension = target_dimension.rename(columns={"month": "reporting_month"})
    return safe_many_to_one_merge(
        result,
        target_dimension,
        on="reporting_month",
        right_name="monthly targets",
    )


def merge_inventory_with_products(inventory: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    products_dimension = _dimension_columns(products, ("product_id",), prefix="product_")
    return safe_many_to_one_merge(
        inventory, products_dimension, on="product_id", right_name="products"
    )


def merge_returns_with_orders_and_products(
    returns: pd.DataFrame, orders: pd.DataFrame, products: pd.DataFrame
) -> pd.DataFrame:
    order_columns = [
        column
        for column in ("order_id", "product_id", "order_date", "quantity", "unit_price")
        if column in orders
    ]
    order_dimension = orders[order_columns].rename(
        columns={
            "order_date": "original_order_date",
            "quantity": "sold_quantity",
            "unit_price": "original_unit_price",
        }
    )
    merged = safe_many_to_one_merge(
        returns,
        order_dimension,
        on=["order_id", "product_id"],
        right_name="orders",
    )
    product_dimension = _dimension_columns(products, ("product_id",), prefix="product_")
    return safe_many_to_one_merge(merged, product_dimension, on="product_id", right_name="products")
