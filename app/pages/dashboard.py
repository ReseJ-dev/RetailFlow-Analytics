"""Interactive management dashboard page."""

from collections.abc import Mapping

import pandas as pd
import streamlit as st

from app.components.charts import render_dashboard_charts
from app.components.empty_state import render_empty_state
from app.components.filter_bar import render_filter_bar
from app.components.header import render_page_header
from app.components.kpi_card import render_kpi_card
from app.components.layout import navigate_and_rerun
from app.components.recommendation_card import render_recommendations
from app.services.dashboard_service import (
    DashboardFilters,
    DashboardResult,
    calculate_dashboard,
    derive_filter_options,
)
from app.services.processing_service import has_blocking_structural_errors
from app.state import AppPage, SessionState, StateKey
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
    st.subheader("Product and inventory tables")
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


def render_dashboard(state: SessionState) -> None:
    """Render a consistently filtered dashboard from a valid ProcessingResult."""
    render_page_header(
        page_title="Dashboard",
        description="Explore sales, returns, inventory risks, and rule-based recommendations.",
        reporting_period=state[StateKey.SELECTED_REPORTING_PERIOD.value],
        last_successful_run=state[StateKey.LAST_SUCCESSFUL_RUN.value],
        status=state[StateKey.APPLICATION_STATUS.value],
    )
    processing = state[StateKey.PROCESSING_RESULT.value]
    if not isinstance(processing, ProcessingResult) or has_blocking_structural_errors(processing):
        render_empty_state(
            "Validated data required",
            "No validated dataset is available. Upload and validate your source files first.",
        )
        if st.button("Go to Upload Data", type="primary"):
            navigate_and_rerun(state, AppPage.UPLOAD_DATA)
        return

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
    kpi_columns = st.columns(6)
    for column, card in zip(kpi_columns, result.kpi_cards, strict=True):
        with column:
            render_kpi_card(card, result.currency)
    st.subheader("Performance charts")
    render_dashboard_charts(result.charts, result.currency)
    _render_tables(result)
    render_recommendations(result.recommendations)


__all__ = ["render_dashboard"]
