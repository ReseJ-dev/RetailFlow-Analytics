"""Data cleaning, normalization, and currency conversion."""

from retailflow.transformation.cleaner import (
    DataCleaner,
    DuplicateStrategy,
    TransformationResult,
    TransformationStatistics,
    clean_dataset,
)
from retailflow.transformation.currency_converter import (
    CurrencyConverter,
    UnsupportedCurrencyError,
)
from retailflow.transformation.merger import (
    merge_inventory_with_products,
    merge_orders_with_products,
    merge_orders_with_targets,
    merge_returns_with_orders_and_products,
    safe_many_to_one_merge,
)
from retailflow.transformation.normalizer import (
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

__all__ = [
    "CurrencyConverter",
    "DataCleaner",
    "DuplicateStrategy",
    "TransformationResult",
    "TransformationStatistics",
    "UnsupportedCurrencyError",
    "clean_dataset",
    "merge_inventory_with_products",
    "merge_orders_with_products",
    "merge_orders_with_targets",
    "merge_returns_with_orders_and_products",
    "normalize_country",
    "normalize_currency",
    "normalize_identifier",
    "normalize_order_status",
    "normalize_sales_channel",
    "normalize_string",
    "parse_date",
    "parse_integer",
    "parse_number",
    "safe_many_to_one_merge",
]
