"""Dashboard KPI card with period comparison semantics."""

from decimal import Decimal

import streamlit as st

from app.services.dashboard_service import ComparisonType, DashboardKPI


def _value(card: DashboardKPI, currency: str) -> str:
    numeric = float(card.value)
    if card.monetary:
        return f"{numeric:,.2f} {currency}"
    if card.rate:
        return f"{numeric:.1f}%"
    return f"{int(numeric):,}"


def _delta(card: DashboardKPI) -> str | None:
    comparison = card.comparison
    if comparison is None:
        return None
    difference: Decimal | None
    suffix: str
    if card.comparison_type is ComparisonType.PERCENTAGE_POINTS:
        difference = comparison.percentage_point_difference
        suffix = " pp"
    else:
        difference = comparison.percentage_difference
        suffix = "%"
    return None if difference is None else f"{float(difference):+.1f}{suffix} vs previous"


def render_kpi_card(card: DashboardKPI, currency: str) -> None:
    """Render one KPI value, comparison unit, direction, and explanation."""
    delta = _delta(card)
    st.metric(
        card.label,
        _value(card, currency),
        delta=delta or "No previous-period baseline",
        delta_color=("inverse" if card.field == "return_rate_percent" else "normal"),
        help=card.caption,
        border=True,
    )
    st.caption(
        f"Direction: {card.direction.value}. Comparison type: "
        f"{card.comparison_type.value}. {card.caption}"
    )
