from __future__ import annotations

from app.components.filter_bar import _WIDGET_KEYS, _reset_widgets
from app.pages.dashboard import _dashboard_kpi_cards, _header_context
from app.services.dashboard_service import (
    DashboardFilters,
    calculate_dashboard,
    derive_filter_options,
)
from app.state import AppPage, StateKey
from streamlit.testing.v1 import AppTest

from .test_dashboard_service import _processing_result


def test_dashboard_kpi_view_preserves_existing_values_and_adds_supported_metrics() -> None:
    processing = _processing_result()
    result = calculate_dashboard(
        processing.processed_orders,
        processing.inventory,
        processing.returns,
        DashboardFilters(),
        default_currency="EUR",
    )

    cards = _dashboard_kpi_cards(result)
    by_field = {card.field: card for card in cards}

    assert tuple(card.field for card in cards) == (
        "net_revenue",
        "gross_profit",
        "gross_margin_percent",
        "orders",
        "units_sold",
        "average_order_value",
        "return_rate_percent",
        "available_stock",
    )
    assert all(
        by_field[existing.field].value == existing.value for existing in result.kpi_cards
    )
    assert by_field["units_sold"].value == result.kpis.units_sold
    assert by_field["available_stock"].value == result.inventory_metrics[
        "available_stock"
    ].sum()


def test_filter_reset_restores_full_period_and_clears_all_dimensions() -> None:
    processing = _processing_result()
    options = derive_filter_options(processing.processed_orders, processing.inventory)
    state: dict[str, object] = {key: ["selected"] for key in _WIDGET_KEYS.values()}
    state[StateKey.ACTIVE_FILTERS.value] = DashboardFilters(countries=("Cyprus",))

    _reset_widgets(state, options)

    assert state[_WIDGET_KEYS["dates"]] == (options.minimum_date, options.maximum_date)
    assert all(
        state[key] == [] for name, key in _WIDGET_KEYS.items() if name != "dates"
    )
    assert state[StateKey.ACTIVE_FILTERS.value] == DashboardFilters()


def test_dashboard_header_reports_period_and_existing_quality_score() -> None:
    processing = _processing_result()
    state: dict[str, object] = {
        StateKey.SELECTED_REPORTING_PERIOD.value: None,
        StateKey.LAST_SUCCESSFUL_RUN.value: None,
    }

    context = _header_context(state, processing)

    assert context[0] == "Reporting period: 01 Jan 2025–01 Jan 2025"
    assert context[1].startswith("Data quality: ")
    assert context[1].endswith("data health")


def test_dashboard_page_renders_shared_filters_kpis_charts_and_recommendation_groups() -> None:
    app = AppTest.from_file("app/main.py", default_timeout=15).run()
    app.session_state[StateKey.PROCESSING_RESULT.value] = _processing_result()
    app.session_state[StateKey.CURRENT_PAGE.value] = AppPage.DASHBOARD

    app = app.run()

    assert not app.exception
    assert app.title[0].value == "Dashboard"
    assert [metric.label for metric in app.metric] == [
        "Net Revenue",
        "Gross Profit",
        "Gross Margin",
        "Orders",
        "Units Sold",
        "Average Order Value",
        "Return Rate",
        "Available Stock",
    ]
    assert [control.label for control in app.multiselect[:8]] == [
        "Country",
        "Product category",
        "Supplier",
        "Sales channel",
        "Warehouse",
        "Product",
        "Currency",
        "Order status",
    ]
    assert len(app.get("plotly_chart")) == 8
    assert any(tab.label.startswith("Critical (") for tab in app.tabs)
    assert any(button.label == "Reset Filters" for button in app.button)
