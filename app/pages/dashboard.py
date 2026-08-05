"""Interactive management dashboard page."""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import streamlit as st

from app.components.charts import render_dashboard_charts
from app.components.empty_state import render_empty_state
from app.components.filter_bar import render_filter_bar
from app.components.kpi_card import render_kpi_card
from app.components.layout import navigate_and_rerun
from app.components.quality_summary import quality_score_interpretation
from app.components.recommendation_card import render_recommendations
from app.components.ui import page_header, section_header
from app.services.dashboard_service import (
    ComparisonDirection,
    ComparisonType,
    DashboardFilters,
    DashboardKPI,
    DashboardResult,
    calculate_dashboard,
    derive_filter_options,
)
from app.services.processing_service import build_quality_summary, has_blocking_structural_errors
from app.state import AppPage, SessionState, StateKey
from retailflow.analytics import MetricComparison
from retailflow.models import ProcessingResult


@st.cache_data(show_spinner=False)
def _cached_dashboard(
    orders: pd.DataFrame,
    inventory: pd.DataFrame,
    returns: pd.DataFrame,
    filters: DashboardFilters,
    inventory_thresholds: dict[str, object] | None,
    default_currency: str,
) -> DashboardResult:
    """Cache analytics from stable frame values rather than mutable session state."""
    return calculate_dashboard(
        orders,
        inventory,
        returns,
        filters,
        inventory_thresholds=inventory_thresholds,
        default_currency=default_currency,
    )


def _dashboard_settings(
    state: SessionState,
) -> tuple[dict[str, object] | None, str]:
    raw = state[StateKey.REPORT_SETTINGS.value]
    if not isinstance(raw, Mapping):
        return None, "USD"
    inventory_value = raw.get("inventory_thresholds", raw.get("inventory"))
    thresholds = (
        {str(key): value for key, value in inventory_value.items()}
        if isinstance(inventory_value, Mapping)
        else None
    )
    report_value = raw.get("report")
    nested_report = report_value if isinstance(report_value, Mapping) else {}
    currency = str(raw.get("default_currency", nested_report.get("default_currency", "USD")))
    return thresholds, currency


def _csv_download(frame: pd.DataFrame, filename: str) -> None:
    st.download_button(
        "Download CSV",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        disabled=frame.empty,
    )


def _render_table(title: str, frame: pd.DataFrame, filename: str) -> None:
    st.markdown(f"#### {title}")
    if frame.empty:
        st.info(f"No records are available for {title.lower()}.")
        return
    st.dataframe(frame, hide_index=True, width="stretch")
    _csv_download(frame, filename)


def _render_tables(result: DashboardResult) -> None:
    section_header(
        "Product and inventory detail",
        "Review filtered product performance and inventory exceptions; download any view as CSV.",
    )
    tables = result.tables
    tabs = st.tabs(
        [
            "Top products",
            "Return rates",
            "Critical stock",
            "Below reorder",
            "Dead stock",
            "Overstock",
            "No sales",
        ]
    )
    definitions = (
        (
            "Top-performing products",
            tables.top_products,
            "top_performing_products.csv",
        ),
        (
            "Products with highest return rates",
            tables.highest_return_rates,
            "highest_return_rates.csv",
        ),
        (
            "Out-of-stock and critical products",
            tables.out_of_stock_and_critical,
            "critical_stock.csv",
        ),
        (
            "Products below reorder level",
            tables.below_reorder_level,
            "below_reorder_level.csv",
        ),
        ("Dead stock", tables.dead_stock, "dead_stock.csv"),
        ("Overstock", tables.overstock, "overstock.csv"),
        ("Products with no sales", tables.no_sales, "no_sales_products.csv"),
    )
    for tab, (title, frame, filename) in zip(tabs, definitions, strict=True):
        with tab:
            _render_table(title, frame, filename)


def _store_dashboard_result(state: SessionState, result: DashboardResult) -> None:
    state[StateKey.SALES_ANALYTICS.value] = result.sales_analytics
    state[StateKey.INVENTORY_ANALYTICS.value] = result.inventory_metrics
    state[StateKey.RETURNS_ANALYTICS.value] = result.returns_analytics
    state[StateKey.RECOMMENDATIONS.value] = result.recommendations


def _format_date(value: date | None) -> str:
    return value.strftime("%d %b %Y") if value is not None else "Not available"


def _header_context(state: SessionState, processing: ProcessingResult) -> tuple[str, ...]:
    dates = (
        pd.to_datetime(processing.processed_orders["order_date"], errors="coerce").dropna()
        if "order_date" in processing.processed_orders
        else pd.Series(dtype="datetime64[ns]")
    )
    selected_period = state[StateKey.SELECTED_REPORTING_PERIOD.value]
    if selected_period:
        period = str(selected_period)
    elif dates.empty:
        period = "No reporting period available"
    else:
        period = f"{_format_date(dates.min().date())}–{_format_date(dates.max().date())}"
    quality = build_quality_summary(processing)
    interpretation, _ = quality_score_interpretation(quality.quality_score)
    context = [
        f"Reporting period: {period}",
        f"Data quality: {quality.quality_score:.1f}% — {interpretation}",
    ]
    last_run = state[StateKey.LAST_SUCCESSFUL_RUN.value]
    if isinstance(last_run, datetime):
        context.append(f"Last report generated: {last_run.astimezone():%d %b %Y, %H:%M}")
    return tuple(context)


def _direction(comparison: MetricComparison | None) -> ComparisonDirection:
    if comparison is None or comparison.percentage_difference in {None, Decimal("0")}:
        return ComparisonDirection.NEUTRAL
    return (
        ComparisonDirection.POSITIVE
        if comparison.percentage_difference > 0
        else ComparisonDirection.NEGATIVE
    )


def _dashboard_kpi_cards(result: DashboardResult) -> tuple[DashboardKPI, ...]:
    """Add UI views for existing units-sold and available-stock analytics."""
    units_comparison = result.comparisons.metrics.get("units_sold")
    units = DashboardKPI(
        field="units_sold",
        label="Units Sold",
        value=result.kpis.units_sold,
        comparison=units_comparison,
        comparison_type=ComparisonType.PERCENTAGE,
        direction=_direction(units_comparison),
        caption="Completed units sold in the selected reporting period.",
    )
    available_values = (
        result.inventory_metrics["available_stock"].dropna()
        if "available_stock" in result.inventory_metrics
        else pd.Series(dtype=object)
    )
    available_stock = sum((Decimal(str(value)) for value in available_values), Decimal("0"))
    available = DashboardKPI(
        field="available_stock",
        label="Available Stock",
        value=available_stock,
        comparison=None,
        comparison_type=ComparisonType.PERCENTAGE,
        direction=ComparisonDirection.NEUTRAL,
        caption="Current stock less reserved quantity across filtered inventory rows.",
    )
    by_field = {card.field: card for card in (*result.kpi_cards, units, available)}
    order = (
        "net_revenue",
        "gross_profit",
        "gross_margin_percent",
        "orders",
        "units_sold",
        "average_order_value",
        "return_rate_percent",
        "available_stock",
    )
    return tuple(by_field[field] for field in order)


def _render_kpis(result: DashboardResult) -> None:
    section_header(
        "Performance snapshot",
        "Current values and like-for-like previous-period comparisons.",
    )
    cards = _dashboard_kpi_cards(result)
    for start in range(0, len(cards), 4):
        columns = st.columns(4)
        for column, card in zip(columns, cards[start : start + 4], strict=True):
            with column:
                render_kpi_card(card, result.currency)


def render_dashboard(state: SessionState) -> None:
    """Render a consistently filtered dashboard from a valid ProcessingResult."""
    processing = state[StateKey.PROCESSING_RESULT.value]
    if not isinstance(processing, ProcessingResult) or has_blocking_structural_errors(processing):
        page_header(
            "Dashboard",
            "Explore sales, returns, inventory health, and rule-based recommendations.",
            context=("Validated data required",),
        )
        render_empty_state(
            "Validated data required",
            "No validated dataset is available. Upload and validate your source files first.",
        )
        if st.button("Go to Upload Data", type="primary"):
            navigate_and_rerun(state, AppPage.UPLOAD_DATA)
        return

    page_header(
        "Dashboard",
        "Explore sales, returns, inventory health, and rule-based recommendations.",
        context=_header_context(state, processing),
    )
    options = derive_filter_options(processing.processed_orders, processing.inventory)
    filters = render_filter_bar(state, options)
    thresholds, default_currency = _dashboard_settings(state)
    with st.spinner("Preparing dashboard analytics..."):
        result = _cached_dashboard(
            processing.processed_orders,
            processing.inventory,
            processing.returns,
            filters,
            thresholds,
            default_currency,
        )
    _store_dashboard_result(state, result)
    summary = result.filtered_summary
    st.caption(
        f"{summary.filtered_order_rows:,} completed order rows · "
        f"{summary.filtered_inventory_rows:,} inventory rows · "
        f"{summary.filtered_return_rows:,} return rows"
    )
    if result.filtered_orders.empty:
        st.warning("No completed orders match the selected filters.")
    _render_kpis(result)
    section_header(
        "Performance charts",
        "All charts use the same filtered analytics result and shared Plotly theme.",
    )
    render_dashboard_charts(result.charts, result.currency)
    _render_tables(result)
    render_recommendations(result.recommendations)


__all__ = ["render_dashboard"]
