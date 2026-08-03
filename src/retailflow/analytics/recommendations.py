"""Transparent deterministic recommendations derived from inventory metrics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

import pandas as pd

from retailflow.analytics.inventory_metrics import (
    InventoryStatus,
    coerce_thresholds,
)
from retailflow.analytics.sales_metrics import as_decimal
from retailflow.transformation.normalizer import is_missing


class RecommendationType(StrEnum):
    INVENTORY = "inventory"
    SALES = "sales"
    RETURNS = "returns"
    PRICING = "pricing"
    CATALOGUE = "catalogue"


class RecommendationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class Recommendation:
    recommendation_type: RecommendationType
    severity: RecommendationSeverity
    product_id: str | None
    explanation: str
    supporting_metrics: Mapping[str, object]
    recommended_action: str
    rule_identifier: str

    @property
    def rule_id(self) -> str:
        return self.rule_identifier


def _recommendation(
    recommendation_type: RecommendationType,
    severity: RecommendationSeverity,
    row: pd.Series,
    explanation: str,
    metrics: Mapping[str, object],
    action: str,
    rule_identifier: str,
) -> Recommendation:
    supporting = {"warehouse": row.get("warehouse"), **metrics}
    return Recommendation(
        recommendation_type,
        severity,
        str(row["product_id"]) if not is_missing(row.get("product_id")) else None,
        explanation,
        supporting,
        action,
        rule_identifier,
    )


def _reorder_action(row: pd.Series) -> str:
    quantity = int(row.get("suggested_reorder_quantity", 0))
    return (
        f"Reorder {quantity} units."
        if quantity > 0
        else "Schedule replenishment before the next sale."
    )


def _dead_stock_rule(
    days_since_sale: int, thresholds: tuple[int, int, int]
) -> tuple[str, RecommendationSeverity, int] | None:
    reached = [days for days in thresholds if days_since_sale >= days]
    if not reached:
        return None
    threshold = max(reached)
    severity = (
        RecommendationSeverity.CRITICAL
        if threshold == max(thresholds)
        else RecommendationSeverity.WARNING
    )
    return f"INV_DEAD_STOCK_{threshold}", severity, threshold


def generate_recommendations(
    inventory_metrics: pd.DataFrame,
    *,
    thresholds: object | None = None,
) -> tuple[Recommendation, ...]:
    """Apply deterministic rules; no model or external service is called."""
    configured = coerce_thresholds(thresholds)
    if inventory_metrics.empty:
        return ()
    recommendations: list[Recommendation] = []
    product_rules_emitted: set[tuple[str, str]] = set()
    for _, row in inventory_metrics.sort_values(
        ["product_id", "warehouse"], kind="stable"
    ).iterrows():
        product_id = str(row["product_id"])
        available = as_decimal(row.get("available_stock", 0))
        reorder_level = as_decimal(row.get("reorder_level", 0))
        coverage = (
            None
            if is_missing(row.get("stock_coverage_days"))
            else as_decimal(row["stock_coverage_days"])
        )
        status = str(row.get("inventory_status", ""))

        if status == InventoryStatus.OUT_OF_STOCK.value:
            recommendations.append(
                _recommendation(
                    RecommendationType.INVENTORY,
                    RecommendationSeverity.CRITICAL,
                    row,
                    "Available stock is zero or negative.",
                    {"available_stock": available},
                    _reorder_action(row),
                    "INV_OUT_OF_STOCK",
                )
            )
        if available <= reorder_level:
            recommendations.append(
                _recommendation(
                    RecommendationType.INVENTORY,
                    RecommendationSeverity.WARNING,
                    row,
                    "Available stock is at or below the configured reorder level.",
                    {
                        "available_stock": available,
                        "reorder_level": reorder_level,
                        "suggested_reorder_quantity": int(row.get("suggested_reorder_quantity", 0)),
                    },
                    _reorder_action(row),
                    "INV_BELOW_REORDER_LEVEL",
                )
            )
        if coverage is not None and coverage < configured.critical_coverage_days:
            recommendations.append(
                _recommendation(
                    RecommendationType.INVENTORY,
                    RecommendationSeverity.CRITICAL,
                    row,
                    f"Stock coverage is only {coverage} days, below the critical threshold.",
                    {
                        "stock_coverage_days": coverage,
                        "threshold_days": configured.critical_coverage_days,
                    },
                    _reorder_action(row),
                    f"INV_COVERAGE_LT_{configured.critical_coverage_days}",
                )
            )
        elif coverage is not None and coverage < configured.low_coverage_days:
            recommendations.append(
                _recommendation(
                    RecommendationType.INVENTORY,
                    RecommendationSeverity.WARNING,
                    row,
                    f"Stock coverage is {coverage} days, below the low-stock threshold.",
                    {
                        "stock_coverage_days": coverage,
                        "threshold_days": configured.low_coverage_days,
                    },
                    _reorder_action(row),
                    f"INV_COVERAGE_LT_{configured.low_coverage_days}",
                )
            )
        elif coverage is not None and coverage > configured.overstock_coverage_days:
            recommendations.append(
                _recommendation(
                    RecommendationType.INVENTORY,
                    RecommendationSeverity.WARNING,
                    row,
                    f"Stock coverage is {coverage} days, above the overstock threshold.",
                    {
                        "stock_coverage_days": coverage,
                        "threshold_days": configured.overstock_coverage_days,
                    },
                    "Review excess stock.",
                    f"INV_COVERAGE_GT_{configured.overstock_coverage_days}",
                )
            )

        days_since_sale = row.get("days_since_last_sale")
        if not is_missing(days_since_sale) and available > 0:
            days_since_sale_value = int(str(days_since_sale))
            dead_rule = _dead_stock_rule(days_since_sale_value, configured.dead_stock_days)
            if dead_rule is not None:
                identifier, severity, threshold = dead_rule
                recommendations.append(
                    _recommendation(
                        RecommendationType.INVENTORY,
                        severity,
                        row,
                        f"The product has not sold for {days_since_sale_value} days.",
                        {
                            "days_since_last_sale": days_since_sale_value,
                            "threshold_days": threshold,
                            "available_stock": available,
                        },
                        "Review excess stock and consider a markdown or transfer.",
                        identifier,
                    )
                )

        product_level_rules: Iterable[
            tuple[
                bool,
                str,
                RecommendationType,
                RecommendationSeverity,
                str,
                Mapping[str, object],
                str,
            ]
        ] = (
            (
                bool(row.get("is_high_revenue", False))
                and status in {InventoryStatus.OUT_OF_STOCK.value, InventoryStatus.CRITICAL.value},
                "INV_HIGH_REVENUE_CRITICAL",
                RecommendationType.INVENTORY,
                RecommendationSeverity.CRITICAL,
                "A high-revenue product has critically low stock.",
                {
                    "net_revenue": row.get("net_revenue", Decimal("0")),
                    "stock_coverage_days": row.get("stock_coverage_days"),
                },
                _reorder_action(row),
            ),
            (
                as_decimal(row.get("return_rate_percent", 0)) > configured.high_return_rate_percent,
                "RET_HIGH_RETURN_RATE",
                RecommendationType.RETURNS,
                RecommendationSeverity.WARNING,
                f"The product return rate is {row.get('return_rate_percent')}%.",
                {"return_rate_percent": row.get("return_rate_percent")},
                f"Investigate the {row.get('return_rate_percent')}% return rate.",
            ),
            (
                as_decimal(row.get("purchase_cost", 0)) > as_decimal(row.get("selling_price", 0)),
                "PRICING_COST_ABOVE_SELLING",
                RecommendationType.PRICING,
                RecommendationSeverity.CRITICAL,
                "Purchase cost is higher than the configured selling price.",
                {
                    "purchase_cost": row.get("purchase_cost"),
                    "selling_price": row.get("selling_price"),
                },
                "Review supplier cost and update the selling price.",
            ),
            (
                int(row.get("units_sold", 0)) == 0,
                "SALES_NO_SALES",
                RecommendationType.SALES,
                RecommendationSeverity.WARNING,
                "The product generated no completed sales in the analysis period.",
                {
                    "units_sold": 0,
                    "period_days": row.get("period_days"),
                    "available_stock": available,
                },
                "Review demand, listing visibility, and stocking strategy.",
            ),
            (
                bool(row.get("catalogue_data_missing", False)),
                "CATALOGUE_MISSING_DATA",
                RecommendationType.CATALOGUE,
                RecommendationSeverity.CRITICAL,
                "Required catalogue attributes are missing for this product.",
                {"catalogue_data_missing": True},
                "Update the product catalogue before including these orders.",
            ),
        )
        for (
            condition,
            identifier,
            kind,
            severity,
            explanation,
            metrics,
            action,
        ) in product_level_rules:
            key = (product_id, identifier)
            if condition and key not in product_rules_emitted:
                recommendations.append(
                    _recommendation(
                        kind,
                        severity,
                        row,
                        explanation,
                        metrics,
                        action,
                        identifier,
                    )
                )
                product_rules_emitted.add(key)

    severity_order = {
        RecommendationSeverity.CRITICAL: 0,
        RecommendationSeverity.WARNING: 1,
        RecommendationSeverity.INFO: 2,
    }
    return tuple(
        sorted(
            recommendations,
            key=lambda item: (
                severity_order[item.severity],
                item.rule_identifier,
                item.product_id or "",
                str(item.supporting_metrics.get("warehouse", "")),
            ),
        )
    )


def recommendations_to_dataframe(
    recommendations: Iterable[Recommendation],
) -> pd.DataFrame:
    """Return a report-friendly flat recommendation table."""
    columns = (
        "recommendation_type",
        "severity",
        "product_id",
        "explanation",
        "supporting_metrics",
        "recommended_action",
        "rule_identifier",
    )
    records = [
        {
            "recommendation_type": item.recommendation_type.value,
            "severity": item.severity.value,
            "product_id": item.product_id,
            "explanation": item.explanation,
            "supporting_metrics": dict(item.supporting_metrics),
            "recommended_action": item.recommended_action,
            "rule_identifier": item.rule_identifier,
        }
        for item in recommendations
    ]
    return pd.DataFrame.from_records(records, columns=columns)
