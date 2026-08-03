"""Pure business-rule checks for RetailFlow's canonical datasets."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from retailflow.validation.schemas import DatasetType
from retailflow.validation.validation_result import ValidationIssue, ValidationSeverity

DEFAULT_SUPPORTED_CURRENCIES = frozenset({"CHF", "EUR", "GBP", "USD"})
TARGET_FIELDS = ("revenue_target", "profit_target", "orders_target")
MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@dataclass(frozen=True, slots=True)
class OrderReference:
    """Reference facts needed to validate a return line."""

    order_date: pd.Timestamp | None
    sold_quantity: float


def is_missing(value: Any) -> bool:  # noqa: ANN401 - pandas scalar values are heterogeneous
    """Return whether a scalar is null or blank text."""
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def parse_number(
    value: Any,  # noqa: ANN401 - pandas scalar values are heterogeneous
    *,
    integer: bool = False,
) -> float | None:
    """Parse a finite number and optionally require a whole-number value."""
    if is_missing(value) or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or (integer and not parsed.is_integer()):
        return None
    return parsed


def parse_date(value: Any) -> pd.Timestamp | None:  # noqa: ANN401
    """Parse a scalar date without raising parser exceptions."""
    if is_missing(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else pd.Timestamp(parsed)


def _rows(frame: pd.DataFrame) -> Iterable[tuple[int, pd.Series]]:
    for position, (_, row) in enumerate(frame.iterrows()):
        # Row one contains source headers, so the first data row is row two.
        yield position + 2, row


def _issue(
    dataset: DatasetType,
    filename: str | None,
    row_number: int | None,
    field: str | None,
    code: str,
    message: str,
    value: Any,  # noqa: ANN401
    action: str,
    *,
    severity: ValidationSeverity = ValidationSeverity.ERROR,
    can_continue: bool = False,
) -> ValidationIssue:
    return ValidationIssue(
        severity=severity,
        source_dataset=dataset,
        source_filename=filename,
        row_number=row_number,
        field=field,
        issue_code=code,
        message=message,
        original_value=value,
        recommended_action=action,
        row_can_continue=can_continue,
    )


def validate_orders(
    frame: pd.DataFrame,
    filename: str | None,
    *,
    supported_currencies: frozenset[str] = DEFAULT_SUPPORTED_CURRENCIES,
) -> list[ValidationIssue]:
    """Validate order fields and duplicated order lines."""
    issues: list[ValidationIssue] = []
    for row_number, row in _rows(frame):
        for field, code, label in (
            ("order_id", "missing_order_id", "order ID"),
            ("order_date", "missing_order_date", "order date"),
            ("product_id", "missing_product_id", "product ID"),
        ):
            if field in frame and is_missing(row[field]):
                issues.append(
                    _issue(
                        DatasetType.ORDERS,
                        filename,
                        row_number,
                        field,
                        code,
                        f"The {label} is missing.",
                        row[field],
                        f"Provide a valid {label}.",
                    )
                )

        if "quantity" in frame:
            quantity = parse_number(row["quantity"], integer=True)
            if quantity is None:
                issues.append(
                    _issue(
                        DatasetType.ORDERS,
                        filename,
                        row_number,
                        "quantity",
                        "invalid_quantity",
                        "Quantity must be a whole number.",
                        row["quantity"],
                        "Replace the value with a positive whole number.",
                    )
                )
            elif quantity <= 0:
                issues.append(
                    _issue(
                        DatasetType.ORDERS,
                        filename,
                        row_number,
                        "quantity",
                        "quantity_not_positive",
                        "Quantity must be greater than zero.",
                        row["quantity"],
                        "Enter a quantity greater than zero.",
                    )
                )

        if "unit_price" in frame:
            unit_price = parse_number(row["unit_price"])
            if unit_price is None:
                issues.append(
                    _issue(
                        DatasetType.ORDERS,
                        filename,
                        row_number,
                        "unit_price",
                        "invalid_unit_price",
                        "Unit price must be numeric.",
                        row["unit_price"],
                        "Replace the value with a numeric unit price.",
                    )
                )
            elif unit_price < 0:
                issues.append(
                    _issue(
                        DatasetType.ORDERS,
                        filename,
                        row_number,
                        "unit_price",
                        "negative_unit_price",
                        "Unit price cannot be negative.",
                        row["unit_price"],
                        "Enter a unit price greater than or equal to zero.",
                    )
                )

        if "discount" in frame and not is_missing(row["discount"]):
            discount = parse_number(row["discount"])
            if discount is None or not 0 <= discount <= 1:
                issues.append(
                    _issue(
                        DatasetType.ORDERS,
                        filename,
                        row_number,
                        "discount",
                        "discount_out_of_range",
                        "Discount must be between 0 and 1.",
                        row["discount"],
                        "Enter the discount as a decimal between 0 and 1.",
                    )
                )

        if "currency" in frame and not is_missing(row["currency"]):
            currency = str(row["currency"]).strip().upper()
            if currency not in supported_currencies:
                issues.append(
                    _issue(
                        DatasetType.ORDERS,
                        filename,
                        row_number,
                        "currency",
                        "unsupported_currency",
                        f"Currency '{currency}' is not supported.",
                        row["currency"],
                        f"Use one of: {', '.join(sorted(supported_currencies))}.",
                    )
                )

    if len(frame.columns) > 0:
        for position, duplicated in enumerate(frame.duplicated(keep=False)):
            if duplicated:
                issues.append(
                    _issue(
                        DatasetType.ORDERS,
                        filename,
                        position + 2,
                        None,
                        "duplicated_order_row",
                        "This order row is duplicated.",
                        frame.iloc[position].to_dict(),
                        "Remove the duplicate row or correct the differing line details.",
                    )
                )
    return issues


def validate_products(frame: pd.DataFrame, filename: str | None) -> list[ValidationIssue]:
    """Validate product catalogue values."""
    issues: list[ValidationIssue] = []
    if "product_id" in frame:
        duplicated_ids = frame["product_id"].notna() & frame["product_id"].duplicated(keep=False)
        for position in range(len(frame)):
            if bool(duplicated_ids.iloc[position]):
                issues.append(
                    _issue(
                        DatasetType.PRODUCTS,
                        filename,
                        position + 2,
                        "product_id",
                        "duplicated_product_id",
                        "Product ID must be unique.",
                        frame.iloc[position]["product_id"],
                        "Keep one product row for this ID or assign a unique ID.",
                    )
                )

    for row_number, row in _rows(frame):
        if "product_name" in frame and is_missing(row["product_name"]):
            issues.append(
                _issue(
                    DatasetType.PRODUCTS,
                    filename,
                    row_number,
                    "product_name",
                    "missing_product_name",
                    "Product name is missing.",
                    row["product_name"],
                    "Provide a product name.",
                )
            )
        purchase_cost = None
        if "purchase_cost" in frame:
            purchase_cost = parse_number(row["purchase_cost"])
            if purchase_cost is None:
                issues.append(
                    _issue(
                        DatasetType.PRODUCTS,
                        filename,
                        row_number,
                        "purchase_cost",
                        "invalid_purchase_cost",
                        "Purchase cost must be numeric.",
                        row["purchase_cost"],
                        "Replace the value with a numeric purchase cost.",
                    )
                )
            elif purchase_cost < 0:
                issues.append(
                    _issue(
                        DatasetType.PRODUCTS,
                        filename,
                        row_number,
                        "purchase_cost",
                        "negative_purchase_cost",
                        "Purchase cost cannot be negative.",
                        row["purchase_cost"],
                        "Enter a purchase cost greater than or equal to zero.",
                    )
                )
        if "recommended_price" in frame and purchase_cost is not None:
            recommended_price = parse_number(row["recommended_price"])
            if recommended_price is not None and recommended_price < purchase_cost:
                issues.append(
                    _issue(
                        DatasetType.PRODUCTS,
                        filename,
                        row_number,
                        "recommended_price",
                        "recommended_price_below_cost",
                        "Recommended price is below purchase cost.",
                        row["recommended_price"],
                        (
                            "Review pricing or confirm that the product is intentionally "
                            "sold at a loss."
                        ),
                        severity=ValidationSeverity.WARNING,
                        can_continue=True,
                    )
                )
        if "vat_rate" in frame and not is_missing(row["vat_rate"]):
            vat_rate = parse_number(row["vat_rate"])
            if vat_rate is None or not 0 <= vat_rate <= 1:
                issues.append(
                    _issue(
                        DatasetType.PRODUCTS,
                        filename,
                        row_number,
                        "vat_rate",
                        "invalid_vat_rate",
                        "VAT rate must be between 0 and 1.",
                        row["vat_rate"],
                        "Enter VAT as a decimal between 0 and 1.",
                    )
                )
    return issues


def validate_inventory(
    frame: pd.DataFrame,
    filename: str | None,
    *,
    known_product_ids: frozenset[str] | None,
) -> list[ValidationIssue]:
    """Validate inventory quantities and product references."""
    issues: list[ValidationIssue] = []
    for row_number, row in _rows(frame):
        if known_product_ids is not None and "product_id" in frame:
            product_id = str(row["product_id"]).strip()
            if product_id and product_id not in known_product_ids:
                issues.append(
                    _issue(
                        DatasetType.INVENTORY,
                        filename,
                        row_number,
                        "product_id",
                        "unknown_product_id",
                        "Inventory references an unknown product ID.",
                        row["product_id"],
                        "Add the product to the catalogue or correct the product ID.",
                    )
                )
        values: dict[str, float | None] = {}
        for field, code, label in (
            ("stock_quantity", "negative_stock", "Stock quantity"),
            ("reserved_quantity", "negative_reserved_quantity", "Reserved quantity"),
            ("reorder_level", "negative_reorder_level", "Reorder level"),
        ):
            if field not in frame or is_missing(row[field]):
                continue
            parsed_value = parse_number(row[field])
            values[field] = parsed_value
            if parsed_value is not None and parsed_value < 0:
                issues.append(
                    _issue(
                        DatasetType.INVENTORY,
                        filename,
                        row_number,
                        field,
                        code,
                        f"{label} cannot be negative.",
                        row[field],
                        f"Enter a {label.lower()} greater than or equal to zero.",
                    )
                )
        stock = values.get("stock_quantity")
        reserved = values.get("reserved_quantity")
        if stock is not None and reserved is not None and reserved > stock:
            issues.append(
                _issue(
                    DatasetType.INVENTORY,
                    filename,
                    row_number,
                    "reserved_quantity",
                    "reserved_quantity_exceeds_stock",
                    "Reserved quantity is greater than available stock.",
                    row["reserved_quantity"],
                    "Reduce the reserved quantity or correct the stock quantity.",
                )
            )
        if (
            "last_restock_date" in frame
            and not is_missing(row["last_restock_date"])
            and parse_date(row["last_restock_date"]) is None
        ):
            issues.append(
                _issue(
                    DatasetType.INVENTORY,
                    filename,
                    row_number,
                    "last_restock_date",
                    "invalid_restock_date",
                    "Last restock date is invalid.",
                    row["last_restock_date"],
                    "Use a valid date such as YYYY-MM-DD.",
                )
            )
    return issues


def validate_returns(
    frame: pd.DataFrame,
    filename: str | None,
    *,
    known_product_ids: frozenset[str] | None,
    known_order_ids: frozenset[str] | None,
    order_references: Mapping[tuple[str, str], OrderReference] | None,
) -> list[ValidationIssue]:
    """Validate return values and their product/order references."""
    issues: list[ValidationIssue] = []
    for row_number, row in _rows(frame):
        order_id = str(row["order_id"]).strip() if "order_id" in frame else ""
        product_id = str(row["product_id"]).strip() if "product_id" in frame else ""
        if known_order_ids is not None and order_id and order_id not in known_order_ids:
            issues.append(
                _issue(
                    DatasetType.RETURNS,
                    filename,
                    row_number,
                    "order_id",
                    "unknown_order_id",
                    "Return references an unknown order ID.",
                    row["order_id"],
                    "Correct the order ID or add the referenced order.",
                )
            )
        if known_product_ids is not None and product_id and product_id not in known_product_ids:
            issues.append(
                _issue(
                    DatasetType.RETURNS,
                    filename,
                    row_number,
                    "product_id",
                    "unknown_product_id",
                    "Return references an unknown product ID.",
                    row["product_id"],
                    "Correct the product ID or add the referenced product.",
                )
            )
        quantity = parse_number(row["quantity"], integer=True) if "quantity" in frame else None
        if "quantity" in frame and (quantity is None or quantity <= 0):
            issues.append(
                _issue(
                    DatasetType.RETURNS,
                    filename,
                    row_number,
                    "quantity",
                    "invalid_return_quantity",
                    "Return quantity must be a positive whole number.",
                    row.get("quantity"),
                    "Enter a positive whole-number return quantity.",
                )
            )
        if "refund_amount" in frame:
            refund = parse_number(row["refund_amount"])
            if refund is not None and refund < 0:
                issues.append(
                    _issue(
                        DatasetType.RETURNS,
                        filename,
                        row_number,
                        "refund_amount",
                        "negative_refund_amount",
                        "Refund amount cannot be negative.",
                        row["refund_amount"],
                        "Enter a refund amount greater than or equal to zero.",
                    )
                )
        reference = order_references.get((order_id, product_id)) if order_references else None
        if reference is not None:
            return_date = parse_date(row["return_date"]) if "return_date" in frame else None
            if (
                return_date is not None
                and reference.order_date is not None
                and return_date < reference.order_date
            ):
                issues.append(
                    _issue(
                        DatasetType.RETURNS,
                        filename,
                        row_number,
                        "return_date",
                        "return_date_before_order_date",
                        "Return date is before the matching order date.",
                        row["return_date"],
                        "Correct the return date or matching order reference.",
                    )
                )
            if quantity is not None and quantity > reference.sold_quantity:
                issues.append(
                    _issue(
                        DatasetType.RETURNS,
                        filename,
                        row_number,
                        "quantity",
                        "returned_quantity_exceeds_sold",
                        "Returned quantity is greater than the sold quantity.",
                        row["quantity"],
                        "Reduce the return quantity or correct the matching order.",
                    )
                )
    return issues


def validate_targets(frame: pd.DataFrame, filename: str | None) -> list[ValidationIssue]:
    """Validate monthly target periods and non-negative target values."""
    issues: list[ValidationIssue] = []
    for row_number, row in _rows(frame):
        if "month" in frame:
            month = str(row["month"]).strip()
            if is_missing(row["month"]) or MONTH_PATTERN.fullmatch(month) is None:
                issues.append(
                    _issue(
                        DatasetType.MONTHLY_TARGETS,
                        filename,
                        row_number,
                        "month",
                        "invalid_month",
                        "Target month must use YYYY-MM format.",
                        row["month"],
                        "Enter a valid month such as 2025-01.",
                    )
                )
        for field in TARGET_FIELDS:
            if field not in frame or is_missing(row[field]):
                continue
            value = parse_number(row[field])
            if value is not None and value < 0:
                issues.append(
                    _issue(
                        DatasetType.MONTHLY_TARGETS,
                        filename,
                        row_number,
                        field,
                        "negative_target",
                        f"{field.replace('_', ' ').title()} cannot be negative.",
                        row[field],
                        "Enter a target greater than or equal to zero.",
                    )
                )
    if "month" in frame:
        normalized_months = frame["month"].astype("string").str.strip()
        duplicated = normalized_months.notna() & normalized_months.duplicated(keep=False)
        for position in range(len(frame)):
            if bool(duplicated.iloc[position]):
                issues.append(
                    _issue(
                        DatasetType.MONTHLY_TARGETS,
                        filename,
                        position + 2,
                        "month",
                        "duplicate_target_month",
                        "Target month must be unique.",
                        frame.iloc[position]["month"],
                        "Keep one target row for this month.",
                    )
                )
    return issues


def build_order_references(
    orders: pd.DataFrame | None,
) -> tuple[frozenset[str] | None, dict[tuple[str, str], OrderReference] | None]:
    """Build return-validation lookup data from canonical order rows."""
    if orders is None or not {"order_id", "product_id"}.issubset(orders.columns):
        return None, None
    order_ids = frozenset(
        str(value).strip() for value in orders["order_id"] if not is_missing(value)
    )
    quantities: dict[tuple[str, str], float] = {}
    dates: dict[tuple[str, str], pd.Timestamp | None] = {}
    for _, row in orders.iterrows():
        if is_missing(row["order_id"]) or is_missing(row["product_id"]):
            continue
        key = (str(row["order_id"]).strip(), str(row["product_id"]).strip())
        quantity = parse_number(row["quantity"]) if "quantity" in orders else None
        if quantity is not None and quantity > 0:
            quantities[key] = quantities.get(key, 0.0) + quantity
        if key not in dates:
            dates[key] = parse_date(row["order_date"]) if "order_date" in orders else None
    references = {
        key: OrderReference(order_date=dates.get(key), sold_quantity=quantity)
        for key, quantity in quantities.items()
    }
    return order_ids, references
