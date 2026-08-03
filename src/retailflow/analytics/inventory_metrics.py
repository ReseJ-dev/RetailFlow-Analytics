"""Per-product and warehouse inventory analytics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from math import ceil

import pandas as pd

from retailflow.analytics.models import AnalyticsFilters
from retailflow.analytics.sales_metrics import as_decimal, prepare_sales_data
from retailflow.common.exceptions import DataValidationError
from retailflow.transformation.normalizer import is_missing

REQUIRED_INVENTORY_COLUMNS = frozenset({"product_id", "warehouse", "stock_quantity"})
DAY_QUANTUM = Decimal("0.01")
SALES_QUANTUM = Decimal("0.0001")


class InventoryStatus(StrEnum):
    OUT_OF_STOCK = "Out of Stock"
    CRITICAL = "Critical"
    LOW_STOCK = "Low Stock"
    HEALTHY = "Healthy"
    OVERSTOCK = "Overstock"
    NO_SALES_DATA = "No Sales Data"


@dataclass(frozen=True, slots=True)
class InventoryAnalyticsThresholds:
    """Configurable coverage, inactivity, revenue, and returns thresholds."""

    critical_coverage_days: int = 7
    low_coverage_days: int = 14
    overstock_coverage_days: int = 120
    target_coverage_days: int = 30
    dead_stock_days: tuple[int, int, int] = (30, 60, 90)
    high_return_rate_percent: Decimal = Decimal("10.00")
    high_revenue_percentile: float = 0.75

    def __post_init__(self) -> None:
        if not (
            0 <= self.critical_coverage_days < self.low_coverage_days < self.overstock_coverage_days
        ):
            raise ValueError("coverage thresholds must increase from critical to overstock")
        if self.target_coverage_days < 0:
            raise ValueError("target coverage days cannot be negative")
        if tuple(sorted(self.dead_stock_days)) != self.dead_stock_days:
            raise ValueError("dead-stock thresholds must be sorted")
        if not 0 <= self.high_revenue_percentile <= 1:
            raise ValueError("high revenue percentile must be between zero and one")


def coerce_thresholds(value: object | None) -> InventoryAnalyticsThresholds:
    """Accept native thresholds, mappings, or the application's config model."""
    if value is None:
        return InventoryAnalyticsThresholds()
    if isinstance(value, InventoryAnalyticsThresholds):
        return value
    if isinstance(value, Mapping):
        return InventoryAnalyticsThresholds(**dict(value))
    critical = getattr(value, "critical_coverage_days", None)
    low = getattr(value, "low_coverage_days", None)
    overstock = getattr(value, "overstock_coverage_days", None)
    if all(item is not None for item in (critical, low, overstock)):
        configured_dead = int(getattr(value, "dead_stock_days", 90))
        dead_days = tuple(sorted({30, 60, 90, configured_dead}))[-3:]
        return InventoryAnalyticsThresholds(
            critical_coverage_days=int(str(critical)),
            low_coverage_days=int(str(low)),
            overstock_coverage_days=int(str(overstock)),
            dead_stock_days=dead_days,  # type: ignore[arg-type]
        )
    raise TypeError("Unsupported inventory threshold configuration.")


def _date(value: object | None) -> pd.Timestamp | None:
    if value is None or is_missing(value):
        return None
    parsed = pd.to_datetime(str(value), errors="coerce")
    return None if pd.isna(parsed) else pd.Timestamp(parsed).normalize()


def _resolve_period(
    sold: pd.DataFrame,
    inventory: pd.DataFrame,
    period_start: object | None,
    period_end: object | None,
    as_of_date: object | None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None, pd.Timestamp, int]:
    order_dates = (
        pd.to_datetime(sold["order_date"], errors="coerce").dropna()
        if "order_date" in sold
        else pd.Series(dtype="datetime64[ns]")
    )
    restock_dates = (
        pd.to_datetime(inventory["last_restock_date"], errors="coerce").dropna()
        if "last_restock_date" in inventory
        else pd.Series(dtype="datetime64[ns]")
    )
    start = _date(period_start) or (
        pd.Timestamp(order_dates.min()).normalize() if not order_dates.empty else None
    )
    end = _date(period_end) or (
        pd.Timestamp(order_dates.max()).normalize() if not order_dates.empty else None
    )
    explicit_as_of = _date(as_of_date)
    candidates = [date for date in (end, explicit_as_of) if date is not None]
    if not restock_dates.empty:
        candidates.append(pd.Timestamp(restock_dates.max()).normalize())
    as_of = explicit_as_of or (max(candidates) if candidates else pd.Timestamp("1970-01-01"))
    period_days = (
        max(1, int((end - start).days) + 1) if start is not None and end is not None else 1
    )
    return start, end, as_of, period_days


def _product_attribute(row: pd.Series, name: str) -> object:
    prefixed = f"product_{name}"
    if prefixed in row:
        return row[prefixed]
    return row.get(name, pd.NA)


def _status(
    available_stock: Decimal,
    average_daily_sales: Decimal,
    coverage_days: Decimal | None,
    thresholds: InventoryAnalyticsThresholds,
) -> InventoryStatus:
    if available_stock <= 0:
        return InventoryStatus.OUT_OF_STOCK
    if average_daily_sales <= 0 or coverage_days is None:
        return InventoryStatus.NO_SALES_DATA
    if coverage_days <= thresholds.critical_coverage_days:
        return InventoryStatus.CRITICAL
    if coverage_days <= thresholds.low_coverage_days:
        return InventoryStatus.LOW_STOCK
    if coverage_days > thresholds.overstock_coverage_days:
        return InventoryStatus.OVERSTOCK
    return InventoryStatus.HEALTHY


def calculate_inventory_metrics(
    inventory: pd.DataFrame,
    orders: pd.DataFrame,
    returns: pd.DataFrame | None = None,
    *,
    thresholds: object | None = None,
    period_start: object | None = None,
    period_end: object | None = None,
    as_of_date: object | None = None,
) -> pd.DataFrame:
    """Calculate inventory metrics at product/warehouse grain.

    Orders do not currently identify a fulfilment warehouse, so product sales
    velocity is repeated for each warehouse holding that product. It is never
    allocated or divided using an invented assumption.
    """
    missing = REQUIRED_INVENTORY_COLUMNS - set(inventory.columns)
    if missing:
        raise DataValidationError(
            "Inventory analytics requires canonical processed inventory data.",
            technical_detail=f"Missing columns: {sorted(missing)}",
        )
    configured = coerce_thresholds(thresholds)
    start_filter = _date(period_start)
    end_filter = _date(period_end)
    sales_filters = AnalyticsFilters(date_from=start_filter, date_to=end_filter)
    sold = prepare_sales_data(orders, returns, sales_filters)
    historical_sales = prepare_sales_data(orders, None, None)
    start, end, as_of, period_days = _resolve_period(
        sold, inventory, period_start, period_end, as_of_date
    )

    units_by_product: dict[str, int] = {}
    revenue_by_product: dict[str, Decimal] = {}
    returns_by_product: dict[str, int] = {}
    for product_id, group in sold.groupby("product_id", sort=False):
        key = str(product_id)
        units_by_product[key] = int(group["quantity"].sum())
        revenue_by_product[key] = sum(group["net_revenue"], Decimal("0"))
        returns_by_product[key] = int(group["returned_quantity"].sum())
    last_sale_by_product = {
        str(product_id): pd.Timestamp(group["order_date"].max()).normalize()
        for product_id, group in historical_sales.groupby("product_id", sort=False)
    }

    positive_revenues = [float(value) for value in revenue_by_product.values() if value > 0]
    high_revenue_cutoff = (
        Decimal(str(pd.Series(positive_revenues).quantile(configured.high_revenue_percentile)))
        if positive_revenues
        else Decimal("0")
    )
    records: list[dict[str, object]] = []
    for _, row in inventory.iterrows():
        product_id = str(row["product_id"])
        stock = as_decimal(row["stock_quantity"])
        reserved = as_decimal(row.get("reserved_quantity", 0))
        reorder_level = as_decimal(row.get("reorder_level", 0))
        available = stock - reserved
        units_sold = units_by_product.get(product_id, 0)
        average_exact = Decimal(units_sold) / Decimal(period_days)
        average_daily_sales = average_exact.quantize(SALES_QUANTUM, rounding=ROUND_HALF_UP)
        coverage_exact = available / average_exact if average_exact > 0 else None
        coverage = (
            coverage_exact.quantize(DAY_QUANTUM, rounding=ROUND_HALF_UP)
            if coverage_exact is not None
            else None
        )
        target_stock = max(
            reorder_level,
            Decimal(ceil(average_exact * configured.target_coverage_days)),
        )
        suggested_reorder = max(0, ceil(target_stock - available))
        last_sale = last_sale_by_product.get(product_id)
        last_restock = _date(row.get("last_restock_date"))
        returned_quantity = returns_by_product.get(product_id, 0)
        revenue = revenue_by_product.get(product_id, Decimal("0"))
        raw_product_name = _product_attribute(row, "product_name")
        raw_purchase_cost = _product_attribute(row, "purchase_cost")
        raw_selling_price = _product_attribute(row, "recommended_price")
        purchase_cost = as_decimal(raw_purchase_cost)
        selling_price = as_decimal(raw_selling_price)
        records.append(
            {
                "product_id": product_id,
                "warehouse": row["warehouse"],
                "product_name": raw_product_name,
                "stock_quantity": stock,
                "reserved_quantity": reserved,
                "available_stock": available,
                "reorder_level": reorder_level,
                "average_daily_sales": average_daily_sales,
                "stock_coverage_days": coverage if coverage is not None else pd.NA,
                "reorder_alert": available <= reorder_level,
                "suggested_reorder_quantity": suggested_reorder,
                "last_sale_date": last_sale if last_sale is not None else pd.NaT,
                "days_since_last_sale": (
                    int((as_of - last_sale).days) if last_sale is not None else pd.NA
                ),
                "last_restock_date": last_restock if last_restock is not None else pd.NaT,
                "days_since_last_restock": (
                    int((as_of - last_restock).days) if last_restock is not None else pd.NA
                ),
                "inventory_status": _status(
                    available, average_exact, coverage_exact, configured
                ).value,
                "units_sold": units_sold,
                "net_revenue": revenue,
                "returned_quantity": returned_quantity,
                "return_rate_percent": (
                    (Decimal(returned_quantity) / Decimal(units_sold) * 100).quantize(
                        DAY_QUANTUM, rounding=ROUND_HALF_UP
                    )
                    if units_sold
                    else Decimal("0.00")
                ),
                "purchase_cost": purchase_cost,
                "selling_price": selling_price,
                "catalogue_data_missing": any(
                    is_missing(value)
                    for value in (raw_product_name, raw_purchase_cost, raw_selling_price)
                ),
                "is_high_revenue": revenue > 0 and revenue >= high_revenue_cutoff,
                "period_start": start if start is not None else pd.NaT,
                "period_end": end if end is not None else pd.NaT,
                "period_days": period_days,
                "as_of_date": as_of,
            }
        )
    return pd.DataFrame.from_records(records)


analyze_inventory = calculate_inventory_metrics
