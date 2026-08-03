"""Period-over-period KPI comparisons with safe zero handling."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from decimal import Decimal

from retailflow.analytics.models import MetricComparison, PeriodComparison
from retailflow.analytics.sales_metrics import as_decimal, round_percent

DEFAULT_RATE_FIELDS = frozenset(
    {"gross_margin_percent", "return_rate_percent", "gross_margin", "return_rate"}
)


def compare_values(current: object, previous: object, *, is_rate: bool = False) -> MetricComparison:
    """Compare values; return ``None`` for undefined growth from a zero base."""
    current_value = as_decimal(current)
    previous_value = as_decimal(previous)
    difference = current_value - previous_value
    if previous_value == 0:
        percentage_difference = Decimal("0.00") if current_value == 0 else None
    else:
        percentage_difference = round_percent(difference / abs(previous_value) * Decimal("100"))
    return MetricComparison(
        current=current_value,
        previous=previous_value,
        absolute_difference=difference,
        percentage_difference=percentage_difference,
        percentage_point_difference=(round_percent(difference) if is_rate else None),
    )


def _metric_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError("Period comparison expects KPI dataclasses or metric mappings.")


def compare_periods(
    current: object,
    previous: object,
    *,
    rate_fields: frozenset[str] | set[str] = DEFAULT_RATE_FIELDS,
) -> PeriodComparison:
    """Compare every metric shared by current and previous periods."""
    current_metrics = _metric_mapping(current)
    previous_metrics = _metric_mapping(previous)
    shared = current_metrics.keys() & previous_metrics.keys()
    return PeriodComparison(
        {
            name: compare_values(
                current_metrics[name],
                previous_metrics[name],
                is_rate=name in rate_fields,
            )
            for name in sorted(shared)
        }
    )


compare_kpis = compare_periods
