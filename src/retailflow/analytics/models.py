"""Typed inputs and outputs for sales and returns analytics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import pandas as pd

type DateFilter = date | datetime | str | pd.Timestamp | None
type DimensionFilter = str | tuple[str, ...] | list[str] | set[str] | frozenset[str] | None


@dataclass(frozen=True, slots=True)
class AnalyticsFilters:
    """Optional inclusive filters applied before KPI calculation."""

    date_from: DateFilter = None
    date_to: DateFilter = None
    start_date: DateFilter = None
    end_date: DateFilter = None
    country: DimensionFilter = None
    product_category: DimensionFilter = None
    sales_channel: DimensionFilter = None
    currency: DimensionFilter = None
    order_status: DimensionFilter = None


@dataclass(frozen=True, slots=True)
class SalesKPIs:
    gross_revenue: Decimal = Decimal("0.00")
    discount_amount: Decimal = Decimal("0.00")
    net_revenue: Decimal = Decimal("0.00")
    cost_of_goods_sold: Decimal = Decimal("0.00")
    gross_profit: Decimal = Decimal("0.00")
    gross_margin_percent: Decimal = Decimal("0.00")
    orders: int = 0
    units_sold: int = 0
    average_order_value: Decimal = Decimal("0.00")
    returned_quantity: int = 0
    refund_amount: Decimal = Decimal("0.00")
    return_rate_percent: Decimal = Decimal("0.00")

    @property
    def gross_margin(self) -> Decimal:
        return self.gross_margin_percent

    @property
    def return_rate(self) -> Decimal:
        return self.return_rate_percent

    @property
    def cogs(self) -> Decimal:
        return self.cost_of_goods_sold


@dataclass(frozen=True, slots=True)
class ReturnsKPIs:
    returned_quantity: int = 0
    refund_amount: Decimal = Decimal("0.00")
    return_rate_percent: Decimal = Decimal("0.00")

    @property
    def return_rate(self) -> Decimal:
        return self.return_rate_percent


@dataclass(frozen=True, slots=True)
class SalesAnalyticsResult:
    kpis: SalesKPIs
    enriched_orders: pd.DataFrame
    daily_revenue: pd.DataFrame
    weekly_revenue: pd.DataFrame
    category_performance: pd.DataFrame
    country_performance: pd.DataFrame
    channel_performance: pd.DataFrame
    top_products_by_revenue: pd.DataFrame
    top_products_by_gross_profit: pd.DataFrame

    @property
    def metrics(self) -> SalesKPIs:
        return self.kpis


@dataclass(frozen=True, slots=True)
class ReturnsAnalyticsResult:
    kpis: ReturnsKPIs
    enriched_returns: pd.DataFrame
    return_reasons: pd.DataFrame
    products_by_return_rate: pd.DataFrame

    @property
    def metrics(self) -> ReturnsKPIs:
        return self.kpis


@dataclass(frozen=True, slots=True)
class MetricComparison:
    """Period-over-period result; percentage change is undefined from zero."""

    current: Decimal
    previous: Decimal
    absolute_difference: Decimal
    percentage_difference: Decimal | None
    percentage_point_difference: Decimal | None = None


@dataclass(frozen=True, slots=True)
class PeriodComparison:
    metrics: dict[str, MetricComparison] = field(default_factory=dict)
