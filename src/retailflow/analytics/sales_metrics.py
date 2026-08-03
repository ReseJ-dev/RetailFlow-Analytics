"""Sales KPI calculation, filtering, and dimensional aggregations."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from retailflow.analytics.models import AnalyticsFilters, SalesAnalyticsResult, SalesKPIs
from retailflow.common.exceptions import DataValidationError
from retailflow.transformation.normalizer import is_missing

MONEY_QUANTUM = Decimal("0.01")
PERCENT_QUANTUM = Decimal("0.01")
REQUIRED_ORDER_COLUMNS = frozenset(
    {"order_id", "order_date", "product_id", "quantity", "unit_price"}
)


def as_decimal(value: object) -> Decimal:
    """Convert source scalars through strings to avoid binary float artifacts."""
    return Decimal("0") if is_missing(value) else Decimal(str(value))


def round_money(value: Decimal) -> Decimal:
    """Round final monetary values to cents using commercial ROUND_HALF_UP."""
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def round_percent(value: Decimal) -> Decimal:
    return value.quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP)


def safe_percentage(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0.00")
    return round_percent(numerator / denominator * Decimal("100"))


def _filter_values(value: object) -> frozenset[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, Iterable):
        return frozenset(str(item) for item in value)
    return frozenset({str(value)})


def _dimension_column(frame: pd.DataFrame, *candidates: str) -> str | None:
    return next((column for column in candidates if column in frame), None)


def filter_orders(orders: pd.DataFrame, filters: AnalyticsFilters | None = None) -> pd.DataFrame:
    """Apply inclusive date and exact dimension filters without mutating input."""
    result = orders.copy(deep=True)
    if filters is None:
        return result
    date_from = filters.date_from if filters.date_from is not None else filters.start_date
    date_to = filters.date_to if filters.date_to is not None else filters.end_date
    if "order_date" in result and (date_from is not None or date_to is not None):
        dates = pd.to_datetime(result["order_date"], errors="coerce")
        if date_from is not None:
            result = result.loc[dates >= pd.Timestamp(date_from)]
            dates = dates.loc[result.index]
        if date_to is not None:
            result = result.loc[dates <= pd.Timestamp(date_to)]

    dimensions = (
        (filters.country, ("country",)),
        (filters.product_category, ("category", "product_category")),
        (filters.sales_channel, ("sales_channel",)),
        (filters.currency, ("currency",)),
        (filters.order_status, ("order_status",)),
    )
    for requested, candidates in dimensions:
        accepted = _filter_values(requested)
        column = _dimension_column(result, *candidates)
        if accepted is not None:
            if column is None:
                return result.iloc[0:0].copy()
            result = result.loc[result[column].astype(str).isin(accepted)]
    return result.reset_index(drop=True)


def _filter_returns_date(returns: pd.DataFrame, filters: AnalyticsFilters | None) -> pd.DataFrame:
    result = returns.copy(deep=True)
    if filters is None or "return_date" not in result:
        return result
    date_from = filters.date_from if filters.date_from is not None else filters.start_date
    date_to = filters.date_to if filters.date_to is not None else filters.end_date
    dates = pd.to_datetime(result["return_date"], errors="coerce")
    if date_from is not None:
        result = result.loc[dates >= pd.Timestamp(date_from)]
        dates = dates.loc[result.index]
    if date_to is not None:
        result = result.loc[dates <= pd.Timestamp(date_to)]
    return result


def _refund_lookup(
    returns: pd.DataFrame | None,
) -> dict[tuple[str, str], tuple[int, Decimal]]:
    lookup: dict[tuple[str, str], tuple[int, Decimal]] = {}
    if returns is None or returns.empty:
        return lookup
    required = {"order_id", "product_id", "quantity", "refund_amount"}
    if not required.issubset(returns.columns):
        return lookup
    for _, row in returns.iterrows():
        key = (str(row["order_id"]), str(row["product_id"]))
        quantity, refund = lookup.get(key, (0, Decimal("0")))
        lookup[key] = (
            quantity + int(as_decimal(row["quantity"])),
            refund + as_decimal(row["refund_amount"]),
        )
    return lookup


def prepare_sales_data(
    orders: pd.DataFrame,
    returns: pd.DataFrame | None = None,
    filters: AnalyticsFilters | None = None,
) -> pd.DataFrame:
    """Return completed order lines enriched with exact Decimal calculations.

    No intermediate monetary value is rounded. Consumers round only final KPI or
    aggregation values with :func:`round_money`, avoiding cumulative line-level
    rounding drift.
    """
    missing = REQUIRED_ORDER_COLUMNS - set(orders.columns)
    if missing:
        raise DataValidationError(
            "Sales analytics requires canonical processed order data.",
            technical_detail=f"Missing columns: {sorted(missing)}",
        )
    filtered = filter_orders(orders, filters)
    if "order_status" in filtered:
        filtered = filtered.loc[
            filtered["order_status"].astype("string").str.casefold().eq("completed")
        ].copy()
    filtered = filtered.reset_index(drop=True)

    filtered_returns = _filter_returns_date(returns, filters) if returns is not None else None
    if filtered_returns is not None and not filtered_returns.empty:
        valid_keys = set(
            zip(filtered["order_id"].astype(str), filtered["product_id"].astype(str), strict=True)
        )
        key_mask = [
            (str(row["order_id"]), str(row["product_id"])) in valid_keys
            for _, row in filtered_returns.iterrows()
        ]
        filtered_returns = filtered_returns.loc[key_mask]
    refunds = _refund_lookup(filtered_returns)

    gross_values: list[Decimal] = []
    discount_values: list[Decimal] = []
    refund_values: list[Decimal] = []
    returned_quantities: list[int] = []
    net_values: list[Decimal] = []
    cost_values: list[Decimal] = []
    profit_values: list[Decimal] = []
    for _, row in filtered.iterrows():
        quantity = as_decimal(row["quantity"])
        gross = quantity * as_decimal(row["unit_price"])
        discount = gross * as_decimal(row.get("discount", 0))
        returned_quantity, refund = refunds.get(
            (str(row["order_id"]), str(row["product_id"])),
            (0, Decimal("0")),
        )
        net = gross - discount - refund
        cost = quantity * as_decimal(row.get("purchase_cost", 0))
        gross_values.append(gross)
        discount_values.append(discount)
        refund_values.append(refund)
        returned_quantities.append(returned_quantity)
        net_values.append(net)
        cost_values.append(cost)
        profit_values.append(net - cost)

    filtered["gross_revenue"] = pd.Series(gross_values, dtype=object)
    filtered["discount_amount"] = pd.Series(discount_values, dtype=object)
    filtered["returned_quantity"] = returned_quantities
    filtered["refund_amount"] = pd.Series(refund_values, dtype=object)
    filtered["net_revenue"] = pd.Series(net_values, dtype=object)
    filtered["cost_of_goods_sold"] = pd.Series(cost_values, dtype=object)
    filtered["gross_profit"] = pd.Series(profit_values, dtype=object)
    return filtered


def calculate_sales_kpis(enriched_orders: pd.DataFrame) -> SalesKPIs:
    if enriched_orders.empty:
        return SalesKPIs()
    gross = sum(enriched_orders["gross_revenue"], Decimal("0"))
    discount = sum(enriched_orders["discount_amount"], Decimal("0"))
    refund = sum(enriched_orders["refund_amount"], Decimal("0"))
    net = sum(enriched_orders["net_revenue"], Decimal("0"))
    cost = sum(enriched_orders["cost_of_goods_sold"], Decimal("0"))
    profit = sum(enriched_orders["gross_profit"], Decimal("0"))
    order_count = int(enriched_orders["order_id"].nunique())
    units = int(enriched_orders["quantity"].sum())
    returned = int(enriched_orders["returned_quantity"].sum())
    return SalesKPIs(
        gross_revenue=round_money(gross),
        discount_amount=round_money(discount),
        net_revenue=round_money(net),
        cost_of_goods_sold=round_money(cost),
        gross_profit=round_money(profit),
        gross_margin_percent=safe_percentage(profit, net),
        orders=order_count,
        units_sold=units,
        average_order_value=(
            round_money(net / Decimal(order_count)) if order_count else Decimal("0.00")
        ),
        returned_quantity=returned,
        refund_amount=round_money(refund),
        return_rate_percent=safe_percentage(Decimal(returned), Decimal(units)),
    )


def _aggregate_performance(
    frame: pd.DataFrame, dimensions: list[str], output_names: list[str] | None = None
) -> pd.DataFrame:
    columns = (output_names or dimensions) + [
        "gross_revenue",
        "discount_amount",
        "refund_amount",
        "net_revenue",
        "cost_of_goods_sold",
        "gross_profit",
        "gross_margin",
        "gross_margin_percent",
        "orders",
        "units_sold",
        "returned_quantity",
        "return_rate",
        "return_rate_percent",
    ]
    if frame.empty or any(column not in frame for column in dimensions):
        return pd.DataFrame(columns=columns)
    records: list[dict[str, object]] = []
    grouped = frame.groupby(dimensions, dropna=False, sort=True)
    for key, group in grouped:
        keys = key if isinstance(key, tuple) else (key,)
        kpis = calculate_sales_kpis(group)
        record: dict[str, object] = dict(zip(output_names or dimensions, keys, strict=True))
        record.update(
            {
                "gross_revenue": kpis.gross_revenue,
                "discount_amount": kpis.discount_amount,
                "refund_amount": kpis.refund_amount,
                "net_revenue": kpis.net_revenue,
                "cost_of_goods_sold": kpis.cost_of_goods_sold,
                "gross_profit": kpis.gross_profit,
                "gross_margin": kpis.gross_margin,
                "gross_margin_percent": kpis.gross_margin_percent,
                "orders": kpis.orders,
                "units_sold": kpis.units_sold,
                "returned_quantity": kpis.returned_quantity,
                "return_rate": kpis.return_rate,
                "return_rate_percent": kpis.return_rate_percent,
            }
        )
        records.append(record)
    return pd.DataFrame.from_records(records, columns=columns)


def daily_revenue(enriched_orders: pd.DataFrame) -> pd.DataFrame:
    frame = enriched_orders.copy()
    if not frame.empty:
        frame["period"] = pd.to_datetime(frame["order_date"]).dt.normalize()
    return _aggregate_performance(frame, ["period"], ["date"])


def weekly_revenue(enriched_orders: pd.DataFrame) -> pd.DataFrame:
    frame = enriched_orders.copy()
    if not frame.empty:
        dates = pd.to_datetime(frame["order_date"])
        frame["period"] = dates.dt.to_period("W-SUN").dt.start_time
    return _aggregate_performance(frame, ["period"], ["week_start"])


def category_performance(enriched_orders: pd.DataFrame) -> pd.DataFrame:
    column = _dimension_column(enriched_orders, "category", "product_category")
    return (
        _aggregate_performance(enriched_orders, [column], ["category"])
        if column
        else _aggregate_performance(pd.DataFrame(), ["category"])
    )


def country_performance(enriched_orders: pd.DataFrame) -> pd.DataFrame:
    return _aggregate_performance(enriched_orders, ["country"])


def channel_performance(enriched_orders: pd.DataFrame) -> pd.DataFrame:
    return _aggregate_performance(enriched_orders, ["sales_channel"])


def product_performance(enriched_orders: pd.DataFrame) -> pd.DataFrame:
    dimensions = ["product_id"]
    if "product_name" in enriched_orders:
        dimensions.append("product_name")
    return _aggregate_performance(enriched_orders, dimensions)


def top_products_by_revenue(enriched_orders: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    return (
        product_performance(enriched_orders)
        .sort_values("net_revenue", ascending=False)
        .head(limit)
        .reset_index(drop=True)
    )


def top_products_by_gross_profit(enriched_orders: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    return (
        product_performance(enriched_orders)
        .sort_values("gross_profit", ascending=False)
        .head(limit)
        .reset_index(drop=True)
    )


def calculate_sales_metrics(
    orders: pd.DataFrame,
    returns: pd.DataFrame | None = None,
    filters: AnalyticsFilters | None = None,
) -> SalesKPIs:
    return calculate_sales_kpis(prepare_sales_data(orders, returns, filters))


def calculate_sales_analytics(
    orders: pd.DataFrame,
    returns: pd.DataFrame | None = None,
    filters: AnalyticsFilters | None = None,
    *,
    top_n: int = 10,
) -> SalesAnalyticsResult:
    enriched = prepare_sales_data(orders, returns, filters)
    return SalesAnalyticsResult(
        kpis=calculate_sales_kpis(enriched),
        enriched_orders=enriched,
        daily_revenue=daily_revenue(enriched),
        weekly_revenue=weekly_revenue(enriched),
        category_performance=category_performance(enriched),
        country_performance=country_performance(enriched),
        channel_performance=channel_performance(enriched),
        top_products_by_revenue=top_products_by_revenue(enriched, top_n),
        top_products_by_gross_profit=top_products_by_gross_profit(enriched, top_n),
    )


calculate_daily_revenue = daily_revenue
calculate_weekly_revenue = weekly_revenue
calculate_category_performance = category_performance
calculate_country_performance = country_performance
calculate_channel_performance = channel_performance
