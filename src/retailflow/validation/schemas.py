"""Canonical dataset schemas used by RetailFlow Analytics."""

from dataclasses import dataclass
from enum import StrEnum

from retailflow.common.exceptions import DataValidationError


class DatasetType(StrEnum):
    """Dataset types supported by the RetailFlow processing pipeline."""

    ORDERS = "orders"
    PRODUCTS = "products"
    INVENTORY = "inventory"
    RETURNS = "returns"
    MONTHLY_TARGETS = "monthly_targets"


@dataclass(frozen=True)
class DatasetSchema:
    """Required and optional canonical columns for one dataset type."""

    dataset_type: DatasetType
    required_columns: tuple[str, ...]
    optional_columns: tuple[str, ...]

    @property
    def all_columns(self) -> tuple[str, ...]:
        """Return every recognized canonical column in display order."""
        return self.required_columns + self.optional_columns


ORDERS_SCHEMA = DatasetSchema(
    dataset_type=DatasetType.ORDERS,
    required_columns=("order_id", "order_date", "product_id", "quantity", "unit_price"),
    optional_columns=(
        "customer_id",
        "discount",
        "currency",
        "country",
        "sales_channel",
        "order_status",
    ),
)

PRODUCTS_SCHEMA = DatasetSchema(
    dataset_type=DatasetType.PRODUCTS,
    required_columns=("product_id", "product_name", "purchase_cost", "recommended_price"),
    optional_columns=("category", "supplier", "vat_rate"),
)

INVENTORY_SCHEMA = DatasetSchema(
    dataset_type=DatasetType.INVENTORY,
    required_columns=("product_id", "warehouse", "stock_quantity"),
    optional_columns=("reserved_quantity", "reorder_level", "last_restock_date"),
)

RETURNS_SCHEMA = DatasetSchema(
    dataset_type=DatasetType.RETURNS,
    required_columns=(
        "return_id",
        "order_id",
        "product_id",
        "return_date",
        "quantity",
        "refund_amount",
    ),
    optional_columns=("return_reason",),
)

MONTHLY_TARGETS_SCHEMA = DatasetSchema(
    dataset_type=DatasetType.MONTHLY_TARGETS,
    required_columns=("month", "revenue_target"),
    optional_columns=("profit_target", "orders_target"),
)

DATASET_SCHEMAS: dict[DatasetType, DatasetSchema] = {
    schema.dataset_type: schema
    for schema in (
        ORDERS_SCHEMA,
        PRODUCTS_SCHEMA,
        INVENTORY_SCHEMA,
        RETURNS_SCHEMA,
        MONTHLY_TARGETS_SCHEMA,
    )
}


def get_dataset_schema(dataset_type: DatasetType | str) -> DatasetSchema:
    """Return the canonical schema for a supported dataset type.

    Raises:
        DataValidationError: If the requested dataset type is unsupported.
    """
    try:
        normalized_type = DatasetType(dataset_type)
    except ValueError as error:
        supported_types = ", ".join(dataset.value for dataset in DatasetType)
        raise DataValidationError(
            f"The dataset type '{dataset_type}' is not supported.",
            technical_detail=f"Supported dataset types: {supported_types}",
        ) from error
    return DATASET_SCHEMAS[normalized_type]
