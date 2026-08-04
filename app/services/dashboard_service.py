"""Dashboard analytics orchestration built exclusively on existing analytics modules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

import pandas as pd

from retailflow.analytics import (
    AnalyticsFilters,
    MetricComparison,
    PeriodComparison,
    Recommendation,
    ReturnsAnalyticsResult,
    SalesAnalyticsResult,
    SalesKPIs,
    calculate_inventory_metrics,
    calculate_returns_analytics,
    calculate_sales_analytics,
    compare_periods,
    filter_orders,
    generate_recommendations,
)
from retailflow.analytics.inventory_metrics import coerce_thresholds


@dataclass(frozen=True, slots=True)
class DashboardFilters:
    """Immutable filter selection suitable for stable Streamlit caching."""

    date_from: date | None = None
    date_to: date | None = None
    countries: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    sales_channels: tuple[str, ...] = ()
    warehouses: tuple[str, ...] = ()
    currencies: tuple[str, ...] = ()
    order_statuses: tuple[str, ...] = ()

    @property
    def active_count(self) -> int:
        """Count selected filter dimensions, treating a date range as one filter."""
        dimensions = (
            self.countries,
            self.categories,
            self.sales_channels,
            self.warehouses,
            self.currencies,
            self.order_statuses,
        )
        return int(self.date_from is not None or self.date_to is not None) + sum(
            bool(value) for value in dimensions
        )


@dataclass(frozen=True, slots=True)
class DashboardFilterOptions:
    """Available filter values derived only from processed data."""

    minimum_date: date | None
    maximum_date: date | None
    countries: tuple[str, ...]
    categories: tuple[str, ...]
    sales_channels: tuple[str, ...]
    warehouses: tuple[str, ...]
    currencies: tuple[str, ...]
    order_statuses: tuple[str, ...]


class ComparisonDirection(StrEnum):
    """Visual meaning of one period-over-period KPI movement."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class ComparisonType(StrEnum):
    """Unit used when displaying a KPI comparison."""

    PERCENTAGE = "percentage"
    PERCENTAGE_POINTS = "percentage points"


@dataclass(frozen=True, slots=True)
class DashboardKPI:
    """One KPI card with raw values and presentation meaning."""

    field: str
    label: str
    value: Decimal | int
    comparison: MetricComparison | None
    comparison_type: ComparisonType
    direction: ComparisonDirection
    caption: str
    monetary: bool = False
    rate: bool = False


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    """Counts and effective period for the filtered dashboard."""

    date_from: date | None
    date_to: date | None
    filtered_order_rows: int
    filtered_inventory_rows: int
    filtered_return_rows: int
    active_filter_count: int


@dataclass(frozen=True, slots=True)
class DashboardChartData:
    """All chart-ready datasets produced once by the service."""

    revenue_over_time: pd.DataFrame
    current_vs_previous: pd.DataFrame
    revenue_by_category: pd.DataFrame
    top_products_by_profit: pd.DataFrame
    sales_by_country: pd.DataFrame
    sales_by_channel: pd.DataFrame
    inventory_risk: pd.DataFrame
    return_reasons: pd.DataFrame


@dataclass(frozen=True, slots=True)
class DashboardTables:
    """Filtered product and inventory exception tables."""

    top_products: pd.DataFrame
    highest_return_rates: pd.DataFrame
    out_of_stock_and_critical: pd.DataFrame
    below_reorder_level: pd.DataFrame
    dead_stock: pd.DataFrame
    overstock: pd.DataFrame
    no_sales: pd.DataFrame


@dataclass(frozen=True, slots=True)
class DashboardResult:
    """Single immutable dashboard result shared by every UI component."""

    filtered_summary: DashboardSummary
    kpis: SalesKPIs
    kpi_cards: tuple[DashboardKPI, ...]
    comparisons: PeriodComparison
    charts: DashboardChartData
    tables: DashboardTables
    recommendations: tuple[Recommendation, ...]
    currency: str
    inventory_metrics: pd.DataFrame
    filtered_orders: pd.DataFrame
    sales_analytics: SalesAnalyticsResult
    returns_analytics: ReturnsAnalyticsResult


def _values(frame: pd.DataFrame, *columns: str) -> tuple[str, ...]:
    column = next((name for name in columns if name in frame), None)
    if column is None:
        return ()
    return tuple(sorted(str(value) for value in frame[column].dropna().unique()))


def derive_filter_options(orders: pd.DataFrame, inventory: pd.DataFrame) -> DashboardFilterOptions:
    """Derive every filter option from the currently processed data."""
    dates = (
        pd.to_datetime(orders["order_date"], errors="coerce").dropna()
        if "order_date" in orders
        else pd.Series(dtype="datetime64[ns]")
    )
    return DashboardFilterOptions(
        minimum_date=dates.min().date() if not dates.empty else None,
        maximum_date=dates.max().date() if not dates.empty else None,
        countries=_values(orders, "country"),
        categories=_values(orders, "category", "product_category"),
        sales_channels=_values(orders, "sales_channel"),
        warehouses=_values(inventory, "warehouse"),
        currencies=_values(orders, "currency"),
        order_statuses=_values(orders, "order_status"),
    )


def _analytics_filters(filters: DashboardFilters) -> AnalyticsFilters:
    return AnalyticsFilters(
        date_from=filters.date_from,
        date_to=filters.date_to,
        country=filters.countries or None,
        product_category=filters.categories or None,
        sales_channel=filters.sales_channels or None,
        currency=filters.currencies or None,
        order_status=filters.order_statuses or None,
    )


def _warehouse_scope(
    orders: pd.DataFrame,
    inventory: pd.DataFrame,
    returns: pd.DataFrame,
    warehouses: tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not warehouses:
        return orders.copy(), inventory.copy(), returns.copy()
    selected_inventory = inventory.loc[inventory["warehouse"].astype(str).isin(warehouses)].copy()
    product_ids = set(selected_inventory["product_id"].astype(str))
    selected_orders = orders.loc[orders["product_id"].astype(str).isin(product_ids)].copy()
    selected_returns = returns.loc[returns["product_id"].astype(str).isin(product_ids)].copy()
    return selected_orders, selected_inventory, selected_returns


def _effective_period(
    orders: pd.DataFrame, filters: DashboardFilters
) -> tuple[date | None, date | None]:
    dates = (
        pd.to_datetime(orders["order_date"], errors="coerce").dropna()
        if "order_date" in orders
        else pd.Series(dtype="datetime64[ns]")
    )
    minimum = dates.min().date() if not dates.empty else None
    maximum = dates.max().date() if not dates.empty else None
    return filters.date_from or minimum, filters.date_to or maximum


def _previous_filters(
    filters: DashboardFilters, start: date | None, end: date | None
) -> AnalyticsFilters:
    if start is None or end is None:
        previous_start = previous_end = None
    else:
        duration = (end - start).days + 1
        previous_end = start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=duration - 1)
    return AnalyticsFilters(
        date_from=previous_start,
        date_to=previous_end,
        country=filters.countries or None,
        product_category=filters.categories or None,
        sales_channel=filters.sales_channels or None,
        currency=filters.currencies or None,
        order_status=filters.order_statuses or None,
    )


def _direction(
    comparison: MetricComparison | None, *, rate: bool, inverse: bool = False
) -> ComparisonDirection:
    if comparison is None:
        return ComparisonDirection.NEUTRAL
    difference = (
        comparison.percentage_point_difference if rate else comparison.percentage_difference
    )
    if difference is None or difference == 0:
        return ComparisonDirection.NEUTRAL
    improved = difference < 0 if inverse else difference > 0
    return ComparisonDirection.POSITIVE if improved else ComparisonDirection.NEGATIVE


def build_kpi_cards(kpis: SalesKPIs, comparisons: PeriodComparison) -> tuple[DashboardKPI, ...]:
    """Build six consistent KPI models, including inverse Return Rate meaning."""
    definitions = (
        (
            "net_revenue",
            "Net Revenue",
            True,
            False,
            "Revenue after discounts and refunds.",
        ),
        (
            "gross_profit",
            "Gross Profit",
            True,
            False,
            "Net revenue less cost of goods sold.",
        ),
        (
            "gross_margin_percent",
            "Gross Margin",
            False,
            True,
            "Gross profit as a percentage of net revenue.",
        ),
        ("orders", "Orders", False, False, "Distinct completed orders."),
        (
            "average_order_value",
            "Average Order Value",
            True,
            False,
            "Net revenue divided by completed orders.",
        ),
        (
            "return_rate_percent",
            "Return Rate",
            False,
            True,
            "Returned units as a percentage of units sold; lower is better.",
        ),
    )
    return tuple(
        DashboardKPI(
            field=field,
            label=label,
            value=getattr(kpis, field),
            comparison=(comparison := comparisons.metrics.get(field)),
            comparison_type=(
                ComparisonType.PERCENTAGE_POINTS if rate else ComparisonType.PERCENTAGE
            ),
            direction=_direction(
                comparison,
                rate=rate,
                inverse=field == "return_rate_percent",
            ),
            caption=caption,
            monetary=monetary,
            rate=rate,
        )
        for field, label, monetary, rate, caption in definitions
    )


def _comparison_chart(current: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    length = max(len(current), len(previous))
    if length == 0:
        return pd.DataFrame(columns=["period_day", "current_period", "previous_period"])
    return pd.DataFrame(
        {
            "period_day": range(1, length + 1),
            "current_period": pd.to_numeric(
                current.get("net_revenue", pd.Series(dtype=float)), errors="coerce"
            ).reindex(range(length)),
            "previous_period": pd.to_numeric(
                previous.get("net_revenue", pd.Series(dtype=float)), errors="coerce"
            ).reindex(range(length)),
        }
    )


def _inventory_distribution(inventory: pd.DataFrame) -> pd.DataFrame:
    if inventory.empty or "inventory_status" not in inventory:
        return pd.DataFrame(columns=["inventory_status", "products"])
    return (
        inventory["inventory_status"]
        .fillna("Unknown")
        .value_counts()
        .rename_axis("inventory_status")
        .reset_index(name="products")
    )


def _inventory_tables(inventory: pd.DataFrame, dead_stock_days: int = 30) -> DashboardTables:
    def rows(mask: pd.Series) -> pd.DataFrame:
        return inventory.loc[mask].reset_index(drop=True)

    if inventory.empty:
        empty = inventory.copy()
        return DashboardTables(empty, empty, empty, empty, empty, empty, empty)
    status = inventory["inventory_status"].astype(str)
    top_products = inventory.sort_values("net_revenue", ascending=False).head(10)
    return DashboardTables(
        top_products=top_products.reset_index(drop=True),
        highest_return_rates=inventory.sort_values("return_rate_percent", ascending=False)
        .head(10)
        .reset_index(drop=True),
        out_of_stock_and_critical=rows(status.isin(["Out of Stock", "Critical"])),
        below_reorder_level=rows(inventory["reorder_alert"].fillna(False).astype(bool)),
        dead_stock=rows(
            pd.to_numeric(inventory["days_since_last_sale"], errors="coerce")
            .ge(dead_stock_days)
            .fillna(False)
            & pd.to_numeric(inventory["available_stock"], errors="coerce").gt(0)
        ),
        overstock=rows(status.eq("Overstock")),
        no_sales=rows(pd.to_numeric(inventory["units_sold"], errors="coerce").eq(0)),
    )


def _threshold_input(value: object | None) -> object | None:
    """Adapt YAML-style dead-stock integers to the analytics threshold model."""
    if not isinstance(value, Mapping):
        return value
    configured = dict(value)
    dead_stock_days = configured.get("dead_stock_days")
    if isinstance(dead_stock_days, int):
        configured["dead_stock_days"] = tuple(sorted({30, 60, 90, dead_stock_days}))[-3:]
    return configured


def calculate_dashboard(
    orders: pd.DataFrame,
    inventory: pd.DataFrame,
    returns: pd.DataFrame,
    filters: DashboardFilters | None = None,
    *,
    inventory_thresholds: object | None = None,
    default_currency: str = "USD",
) -> DashboardResult:
    """Calculate one internally consistent dashboard result from stable frame inputs."""
    selected = filters or DashboardFilters()
    threshold_input = _threshold_input(inventory_thresholds)
    scoped_orders, scoped_inventory, scoped_returns = _warehouse_scope(
        orders, inventory, returns, selected.warehouses
    )
    analytics_filters = _analytics_filters(selected)
    start, end = _effective_period(scoped_orders, selected)
    sales = calculate_sales_analytics(scoped_orders, scoped_returns, analytics_filters)
    returns_analytics = calculate_returns_analytics(
        scoped_orders, scoped_returns, analytics_filters
    )
    previous_sales = calculate_sales_analytics(
        scoped_orders,
        scoped_returns,
        _previous_filters(selected, start, end),
    )
    comparisons = compare_periods(sales.kpis, previous_sales.kpis)
    dimension_filtered_orders = filter_orders(scoped_orders, analytics_filters)
    inventory_metrics = calculate_inventory_metrics(
        scoped_inventory,
        dimension_filtered_orders,
        scoped_returns,
        thresholds=threshold_input,
        period_start=start,
        period_end=end,
        as_of_date=end,
    )
    recommendations = generate_recommendations(inventory_metrics, thresholds=threshold_input)
    configured_thresholds = coerce_thresholds(threshold_input)
    currency_values = _values(sales.enriched_orders, "currency")
    currency = currency_values[0] if len(currency_values) == 1 else default_currency.upper()
    charts = DashboardChartData(
        revenue_over_time=sales.daily_revenue,
        current_vs_previous=_comparison_chart(sales.daily_revenue, previous_sales.daily_revenue),
        revenue_by_category=sales.category_performance.sort_values(
            "net_revenue", ascending=False
        ).reset_index(drop=True),
        top_products_by_profit=sales.top_products_by_gross_profit,
        sales_by_country=sales.country_performance.sort_values(
            "net_revenue", ascending=False
        ).reset_index(drop=True),
        sales_by_channel=sales.channel_performance.sort_values(
            "net_revenue", ascending=False
        ).reset_index(drop=True),
        inventory_risk=_inventory_distribution(inventory_metrics),
        return_reasons=returns_analytics.return_reasons,
    )
    return DashboardResult(
        filtered_summary=DashboardSummary(
            date_from=start,
            date_to=end,
            filtered_order_rows=len(sales.enriched_orders),
            filtered_inventory_rows=len(inventory_metrics),
            filtered_return_rows=len(returns_analytics.enriched_returns),
            active_filter_count=selected.active_count,
        ),
        kpis=sales.kpis,
        kpi_cards=build_kpi_cards(sales.kpis, comparisons),
        comparisons=comparisons,
        charts=charts,
        tables=DashboardTables(
            top_products=sales.top_products_by_revenue,
            highest_return_rates=returns_analytics.products_by_return_rate,
            out_of_stock_and_critical=(
                tables := _inventory_tables(
                    inventory_metrics,
                    min(configured_thresholds.dead_stock_days),
                )
            ).out_of_stock_and_critical,
            below_reorder_level=tables.below_reorder_level,
            dead_stock=tables.dead_stock,
            overstock=tables.overstock,
            no_sales=tables.no_sales,
        ),
        recommendations=recommendations,
        currency=currency,
        inventory_metrics=inventory_metrics,
        filtered_orders=sales.enriched_orders,
        sales_analytics=sales,
        returns_analytics=returns_analytics,
    )


__all__ = [
    "ComparisonDirection",
    "ComparisonType",
    "DashboardChartData",
    "DashboardFilterOptions",
    "DashboardFilters",
    "DashboardKPI",
    "DashboardResult",
    "DashboardSummary",
    "DashboardTables",
    "build_kpi_cards",
    "calculate_dashboard",
    "derive_filter_options",
]
