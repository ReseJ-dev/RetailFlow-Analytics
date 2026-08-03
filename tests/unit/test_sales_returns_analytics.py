"""Manually verifiable tests for sales, returns, and comparisons."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from retailflow.analytics import (
    AnalyticsFilters,
    SalesKPIs,
    calculate_returns_analytics,
    calculate_sales_analytics,
    calculate_sales_metrics,
    compare_periods,
    compare_values,
)


def orders_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": ["O-1", "O-2", "O-3"],
            "order_date": pd.to_datetime(["2025-01-01", "2025-01-08", "2025-01-02"]),
            "product_id": ["P-1", "P-2", "P-1"],
            "product_name": ["Desk", "Chair", "Desk"],
            "category": ["Office", "Home", "Office"],
            "country": ["Cyprus", "Germany", "Cyprus"],
            "sales_channel": ["website", "amazon", "website"],
            "currency": ["USD", "EUR", "USD"],
            "order_status": ["completed", "completed", "pending"],
            "quantity": [2, 1, 5],
            "unit_price": [10, 20, 100],
            "discount": [0.1, 0, 0],
            "purchase_cost": [4, 12, 4],
        }
    )


def returns_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "return_id": ["R-1"],
            "order_id": ["O-1"],
            "product_id": ["P-1"],
            "return_date": pd.to_datetime(["2025-01-03"]),
            "quantity": [1],
            "refund_amount": [9],
            "return_reason": ["Damaged"],
        }
    )


def test_sales_kpis_match_manual_calculation() -> None:
    metrics = calculate_sales_metrics(orders_frame(), returns_frame())

    # O-1: gross 20, discount 2, refund 9, net 9, cost 8, profit 1.
    # O-2: gross/net 20, cost 12, profit 8. Combined profit is 9.
    assert metrics.gross_revenue == Decimal("40.00")
    assert metrics.discount_amount == Decimal("2.00")
    assert metrics.refund_amount == Decimal("9.00")
    assert metrics.net_revenue == Decimal("29.00")
    assert metrics.cost_of_goods_sold == Decimal("20.00")
    assert metrics.gross_profit == Decimal("9.00")
    assert metrics.gross_margin_percent == Decimal("31.03")
    assert metrics.orders == 2
    assert metrics.units_sold == 3
    assert metrics.average_order_value == Decimal("14.50")
    assert metrics.returned_quantity == 1
    assert metrics.return_rate_percent == Decimal("33.33")


@pytest.mark.parametrize(
    "filters",
    [
        AnalyticsFilters(date_from="2025-01-01", date_to="2025-01-01"),
        AnalyticsFilters(country="Cyprus"),
        AnalyticsFilters(product_category="Office"),
        AnalyticsFilters(sales_channel="website"),
        AnalyticsFilters(currency="USD"),
    ],
)
def test_supported_filters_select_the_expected_completed_order(
    filters: AnalyticsFilters,
) -> None:
    metrics = calculate_sales_metrics(orders_frame(), returns_frame(), filters)

    assert metrics.orders == 1
    assert metrics.units_sold == 2
    assert metrics.gross_revenue == Decimal("20.00")


def test_order_status_filter_and_zero_division_are_safe() -> None:
    metrics = calculate_sales_metrics(
        orders_frame(), returns_frame(), AnalyticsFilters(order_status="pending")
    )

    assert metrics == SalesKPIs()


def test_analytics_produces_time_dimension_and_product_aggregations() -> None:
    result = calculate_sales_analytics(orders_frame(), returns_frame())

    assert result.daily_revenue["date"].tolist() == [
        pd.Timestamp("2025-01-01"),
        pd.Timestamp("2025-01-08"),
    ]
    assert result.daily_revenue["net_revenue"].tolist() == [
        Decimal("9.00"),
        Decimal("20.00"),
    ]
    assert result.weekly_revenue["week_start"].tolist() == [
        pd.Timestamp("2024-12-30"),
        pd.Timestamp("2025-01-06"),
    ]
    office = result.category_performance.set_index("category").loc["Office"]
    assert office["net_revenue"] == Decimal("9.00")
    assert set(result.country_performance["country"]) == {"Cyprus", "Germany"}
    assert set(result.channel_performance["sales_channel"]) == {"website", "amazon"}
    assert result.top_products_by_revenue.iloc[0]["product_id"] == "P-2"
    assert result.top_products_by_gross_profit.iloc[0]["product_id"] == "P-2"


def test_returns_reason_and_product_rates_match_manual_calculation() -> None:
    result = calculate_returns_analytics(orders_frame(), returns_frame())

    assert result.kpis.returned_quantity == 1
    assert result.kpis.refund_amount == Decimal("9.00")
    assert result.kpis.return_rate_percent == Decimal("33.33")
    assert result.return_reasons.iloc[0].to_dict() == {
        "return_reason": "Damaged",
        "returns": 1,
        "returned_quantity": 1,
        "refund_amount": Decimal("9.00"),
    }
    first_product = result.products_by_return_rate.iloc[0]
    assert first_product["product_id"] == "P-1"
    assert first_product["return_rate_percent"] == Decimal("50.00")


def test_period_comparisons_include_percentage_and_rate_point_changes() -> None:
    value = compare_values(120, 100)
    rate = compare_values(25, 20, is_rate=True)

    assert value.absolute_difference == Decimal("20")
    assert value.percentage_difference == Decimal("20.00")
    assert value.percentage_point_difference is None
    assert rate.percentage_difference == Decimal("25.00")
    assert rate.percentage_point_difference == Decimal("5.00")
    assert compare_values(10, 0).percentage_difference is None
    assert compare_values(0, 0).percentage_difference == Decimal("0.00")

    current = SalesKPIs(net_revenue=Decimal("120"), gross_margin_percent=Decimal("25"))
    previous = SalesKPIs(net_revenue=Decimal("100"), gross_margin_percent=Decimal("20"))
    comparison = compare_periods(current, previous)
    assert comparison.metrics["net_revenue"].percentage_difference == Decimal("20.00")
    assert comparison.metrics["gross_margin_percent"].percentage_point_difference == Decimal("5.00")


def test_money_rounding_uses_round_half_up() -> None:
    orders = orders_frame().iloc[[0]].copy()
    orders.loc[orders.index[0], "quantity"] = 1
    orders["unit_price"] = orders["unit_price"].astype(object)
    orders.loc[orders.index[0], "unit_price"] = Decimal("1.005")
    orders.loc[orders.index[0], "discount"] = 0
    orders.loc[orders.index[0], "purchase_cost"] = 0

    metrics = calculate_sales_metrics(orders)

    assert metrics.gross_revenue == Decimal("1.01")


def test_zero_net_revenue_has_zero_margin() -> None:
    orders = orders_frame().iloc[[0]].copy()
    returns = returns_frame().copy()
    returns.loc[0, "refund_amount"] = 18

    metrics = calculate_sales_metrics(orders, returns)

    assert metrics.net_revenue == Decimal("0.00")
    assert metrics.gross_margin_percent == Decimal("0.00")
