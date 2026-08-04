"""Tests for consistent service-layer dashboard analytics."""

from decimal import Decimal

from app.services.dashboard_service import (
    ComparisonDirection,
    ComparisonType,
    DashboardFilters,
    build_kpi_cards,
    calculate_dashboard,
    derive_filter_options,
)
from app.services.processing_service import run_processing

from retailflow.analytics import SalesKPIs, compare_periods

from .test_processing_service import _state


def _processing_result():
    state = _state()
    loaded = state["loaded_datasets"]
    assert isinstance(loaded, dict)
    inventory = loaded["inventory"]
    inventory.dataframe["reserved_quantity"] = [0]
    inventory.dataframe["reorder_level"] = [15]
    inventory.dataframe["last_restock_date"] = ["2024-12-01"]
    products = loaded["products"]
    products.dataframe["category"] = ["Office"]
    return run_processing(state)


def test_filter_options_are_derived_from_processed_data() -> None:
    processing = _processing_result()

    options = derive_filter_options(processing.processed_orders, processing.inventory)

    assert options.minimum_date.isoformat() == "2025-01-01"
    assert options.maximum_date.isoformat() == "2025-01-01"
    assert options.warehouses == ("Nicosia",)
    assert options.currencies == ("EUR",)
    assert options.order_statuses == ()


def test_dashboard_reuses_analytics_and_builds_one_consistent_result() -> None:
    processing = _processing_result()

    result = calculate_dashboard(
        processing.processed_orders,
        processing.inventory,
        processing.returns,
        DashboardFilters(),
        default_currency="EUR",
    )

    assert result.kpis.net_revenue == Decimal("20.00")
    assert result.kpis.gross_profit == Decimal("10.00")
    assert result.kpis.orders == 1
    assert result.currency == "EUR"
    assert result.filtered_summary.filtered_order_rows == 1
    assert len(result.kpi_cards) == 6
    assert not result.charts.revenue_over_time.empty
    assert not result.charts.revenue_by_category.empty
    assert not result.tables.out_of_stock_and_critical.empty
    assert not result.tables.below_reorder_level.empty
    assert result.recommendations


def test_dimension_filter_updates_kpis_charts_tables_and_recommendations() -> None:
    processing = _processing_result()
    filters = DashboardFilters(countries=("Country that does not exist",))

    result = calculate_dashboard(
        processing.processed_orders,
        processing.inventory,
        processing.returns,
        filters,
    )

    assert result.kpis.net_revenue == Decimal("0.00")
    assert result.filtered_orders.empty
    assert result.charts.revenue_over_time.empty
    assert result.charts.revenue_by_category.empty
    assert result.tables.top_products.empty
    assert result.inventory_metrics["units_sold"].eq(0).all()
    assert result.tables.no_sales.shape[0] == result.inventory_metrics.shape[0]
    assert all(
        recommendation.supporting_metrics.get("units_sold", 0) == 0
        for recommendation in result.recommendations
        if recommendation.rule_identifier == "SALES_NO_SALES"
    )


def test_warehouse_filter_scopes_orders_and_inventory_by_product() -> None:
    processing = _processing_result()

    selected = calculate_dashboard(
        processing.processed_orders,
        processing.inventory,
        processing.returns,
        DashboardFilters(warehouses=("Nicosia",)),
    )
    missing = calculate_dashboard(
        processing.processed_orders,
        processing.inventory,
        processing.returns,
        DashboardFilters(warehouses=("Unknown warehouse",)),
    )

    assert selected.kpis.orders == 1
    assert selected.filtered_summary.filtered_inventory_rows == 1
    assert missing.kpis.orders == 0
    assert missing.inventory_metrics.empty
    assert not missing.recommendations


def test_return_rate_reduction_is_a_positive_percentage_point_change() -> None:
    current = SalesKPIs(return_rate_percent=Decimal("5.00"))
    previous = SalesKPIs(return_rate_percent=Decimal("10.00"))
    comparison = compare_periods(current, previous)

    cards = build_kpi_cards(current, comparison)
    return_rate = next(card for card in cards if card.field == "return_rate_percent")

    assert return_rate.comparison_type is ComparisonType.PERCENTAGE_POINTS
    assert return_rate.direction is ComparisonDirection.POSITIVE
    assert return_rate.comparison is not None
    assert return_rate.comparison.percentage_point_difference == Decimal("-5.00")


def test_empty_warehouse_filter_result_is_graceful() -> None:
    processing = _processing_result()

    result = calculate_dashboard(
        processing.processed_orders,
        processing.inventory,
        processing.returns,
        DashboardFilters(warehouses=("Missing",), countries=("Missing",)),
    )

    assert result.kpis == SalesKPIs()
    assert result.charts.inventory_risk.empty
    assert result.tables.dead_stock.empty
    assert result.filtered_summary.active_filter_count == 2
