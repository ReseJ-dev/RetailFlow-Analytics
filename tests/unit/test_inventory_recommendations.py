"""Unit tests for inventory coverage and deterministic recommendation rules."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from retailflow.analytics import (
    InventoryAnalyticsThresholds,
    InventoryStatus,
    RecommendationSeverity,
    calculate_inventory_metrics,
    generate_recommendations,
    recommendations_to_dataframe,
)


def inventory_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "product_id": ["P-OUT", "P-CRIT", "P-LOW", "P-OK", "P-OVER", "P-NONE"],
            "warehouse": ["Main"] * 6,
            "product_name": ["Out", "Critical", "Low", "Healthy", "Excess", "Never Sold"],
            "stock_quantity": [0, 5, 30, 60, 300, 50],
            "reserved_quantity": [0, 0, 5, 0, 0, 0],
            "reorder_level": [5, 10, 30, 20, 20, 10],
            "last_restock_date": ["2025-01-01"] * 6,
            "purchase_cost": [5, 10, 5, 12, 5, 5],
            "recommended_price": [10, 1000, 10, 10, 10, 10],
        }
    )


def orders_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": ["O-OUT", "O-CRIT", "O-LOW", "O-OK", "O-OVER"],
            "order_date": pd.to_datetime(
                ["2025-01-10", "2025-01-01", "2025-01-01", "2025-01-01", "2025-01-01"]
            ),
            "product_id": ["P-OUT", "P-CRIT", "P-LOW", "P-OK", "P-OVER"],
            "product_name": ["Out", "Critical", "Low", "Healthy", "Excess"],
            "quantity": [10, 20, 20, 20, 10],
            "unit_price": [10, 1000, 10, 10, 10],
            "discount": [0, 0, 0, 0, 0],
            "purchase_cost": [5, 10, 5, 12, 5],
            "order_status": ["completed"] * 5,
        }
    )


def returns_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "return_id": ["R-1"],
            "order_id": ["O-CRIT"],
            "product_id": ["P-CRIT"],
            "return_date": pd.to_datetime(["2025-01-10"]),
            "quantity": [4],
            "refund_amount": [4000],
            "return_reason": ["Defective"],
        }
    )


def metrics_frame() -> pd.DataFrame:
    return calculate_inventory_metrics(
        inventory_frame(),
        orders_frame(),
        returns_frame(),
        period_start="2025-01-01",
        period_end="2025-01-10",
        as_of_date="2025-04-10",
    )


def test_inventory_metrics_cover_threshold_statuses_and_available_stock() -> None:
    metrics = metrics_frame().set_index("product_id")

    assert metrics.loc["P-OUT", "available_stock"] == Decimal("0")
    assert metrics.loc["P-OUT", "inventory_status"] == InventoryStatus.OUT_OF_STOCK.value
    assert metrics.loc["P-CRIT", "inventory_status"] == InventoryStatus.CRITICAL.value
    assert metrics.loc["P-LOW", "inventory_status"] == InventoryStatus.LOW_STOCK.value
    assert metrics.loc["P-OK", "inventory_status"] == InventoryStatus.HEALTHY.value
    assert metrics.loc["P-OVER", "inventory_status"] == InventoryStatus.OVERSTOCK.value
    assert metrics.loc["P-NONE", "inventory_status"] == InventoryStatus.NO_SALES_DATA.value
    assert metrics.loc["P-NONE", "average_daily_sales"] == Decimal("0.0000")
    assert pd.isna(metrics.loc["P-NONE", "stock_coverage_days"])


def test_suggested_reorder_quantity_targets_configured_coverage() -> None:
    metrics = metrics_frame().set_index("product_id")

    # P-LOW sells 20 units / 10 days = 2 per day. The 30-day target is
    # 60 units; 60 target - 25 available = 35 units to reorder.
    assert metrics.loc["P-LOW", "average_daily_sales"] == Decimal("2.0000")
    assert metrics.loc["P-LOW", "stock_coverage_days"] == Decimal("12.50")
    assert bool(metrics.loc["P-LOW", "reorder_alert"])
    assert metrics.loc["P-LOW", "suggested_reorder_quantity"] == 35
    assert metrics.loc["P-OUT", "suggested_reorder_quantity"] == 30
    assert metrics.loc["P-OK", "suggested_reorder_quantity"] == 0


def test_configurable_thresholds_change_status_deterministically() -> None:
    thresholds = InventoryAnalyticsThresholds(
        critical_coverage_days=3,
        low_coverage_days=10,
        overstock_coverage_days=200,
        target_coverage_days=20,
    )
    metrics = calculate_inventory_metrics(
        inventory_frame(),
        orders_frame(),
        period_start="2025-01-01",
        period_end="2025-01-10",
        thresholds=thresholds,
    ).set_index("product_id")

    assert metrics.loc["P-LOW", "inventory_status"] == InventoryStatus.HEALTHY.value
    assert metrics.loc["P-LOW", "suggested_reorder_quantity"] == 15


def test_dates_since_last_sale_and_restock_use_explicit_as_of_date() -> None:
    metrics = metrics_frame().set_index("product_id")

    assert metrics.loc["P-OUT", "days_since_last_sale"] == 90
    assert metrics.loc["P-OUT", "days_since_last_restock"] == 99
    assert pd.isna(metrics.loc["P-NONE", "days_since_last_sale"])


def test_last_sale_uses_history_outside_velocity_period() -> None:
    historical = orders_frame().copy()
    older_sale = historical.iloc[[0]].copy()
    older_sale["order_id"] = "O-HISTORY"
    older_sale["product_id"] = "P-NONE"
    older_sale["order_date"] = pd.Timestamp("2024-12-01")
    historical = pd.concat([historical, older_sale], ignore_index=True)

    metrics = calculate_inventory_metrics(
        inventory_frame(),
        historical,
        period_start="2025-01-01",
        period_end="2025-01-10",
        as_of_date="2025-02-01",
    ).set_index("product_id")

    assert metrics.loc["P-NONE", "units_sold"] == 0
    assert metrics.loc["P-NONE", "days_since_last_sale"] == 62


def test_recommendations_cover_inventory_returns_pricing_and_no_sales_rules() -> None:
    recommendations = generate_recommendations(metrics_frame())
    rules = {item.rule_identifier for item in recommendations}

    assert {
        "INV_OUT_OF_STOCK",
        "INV_BELOW_REORDER_LEVEL",
        "INV_COVERAGE_LT_7",
        "INV_COVERAGE_LT_14",
        "INV_COVERAGE_GT_120",
        "INV_DEAD_STOCK_90",
        "INV_HIGH_REVENUE_CRITICAL",
        "RET_HIGH_RETURN_RATE",
        "PRICING_COST_ABOVE_SELLING",
        "SALES_NO_SALES",
    } <= rules

    low_stock = next(
        item
        for item in recommendations
        if item.product_id == "P-LOW" and item.rule_identifier == "INV_BELOW_REORDER_LEVEL"
    )
    assert low_stock.recommended_action == "Reorder 35 units."
    assert low_stock.supporting_metrics["suggested_reorder_quantity"] == 35

    excess = next(item for item in recommendations if item.rule_identifier == "INV_COVERAGE_GT_120")
    assert excess.recommended_action == "Review excess stock."

    return_rate = next(
        item for item in recommendations if item.rule_identifier == "RET_HIGH_RETURN_RATE"
    )
    assert return_rate.product_id == "P-CRIT"
    assert "20.00% return rate" in return_rate.recommended_action
    assert return_rate.severity is RecommendationSeverity.WARNING


def test_recommendations_are_deterministic_and_exportable() -> None:
    first = generate_recommendations(metrics_frame())
    second = generate_recommendations(metrics_frame())

    assert first == second
    report = recommendations_to_dataframe(first)
    assert list(report.columns) == [
        "recommendation_type",
        "severity",
        "product_id",
        "explanation",
        "supporting_metrics",
        "recommended_action",
        "rule_identifier",
    ]
    assert report["rule_identifier"].notna().all()
    assert report["recommended_action"].str.len().gt(0).all()
