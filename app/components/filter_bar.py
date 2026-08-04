"""Shared dashboard filter controls."""

from datetime import date, datetime

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from app.services.dashboard_service import DashboardFilterOptions, DashboardFilters
from app.state import SessionState, StateKey

_WIDGET_KEYS = {
    "dates": "dashboard_filter_dates",
    "countries": "dashboard_filter_countries",
    "categories": "dashboard_filter_categories",
    "channels": "dashboard_filter_channels",
    "warehouses": "dashboard_filter_warehouses",
    "currencies": "dashboard_filter_currencies",
    "statuses": "dashboard_filter_statuses",
}


def _current(state: SessionState) -> DashboardFilters:
    value = state[StateKey.ACTIVE_FILTERS.value]
    return value if isinstance(value, DashboardFilters) else DashboardFilters()


def _valid(values: tuple[str, ...], options: tuple[str, ...]) -> list[str]:
    available = set(options)
    return [value for value in values if value in available]


def _reset_widgets(state: SessionState, options: DashboardFilterOptions) -> None:
    state[_WIDGET_KEYS["dates"]] = (
        (options.minimum_date, options.maximum_date)
        if options.minimum_date is not None and options.maximum_date is not None
        else ()
    )
    for key in _WIDGET_KEYS.values():
        if key != _WIDGET_KEYS["dates"]:
            state[key] = []
    state[StateKey.ACTIVE_FILTERS.value] = DashboardFilters()


def _date_range(value: object) -> tuple[date | None, date | None]:
    if isinstance(value, (tuple, list)) and len(value) == 2:
        start, end = value
        return (
            start if isinstance(start, date) else None,
            end if isinstance(end, date) else None,
        )
    return None, None


def _multiselect(
    column: DeltaGenerator,
    label: str,
    options: tuple[str, ...],
    default: list[str],
    key: str,
    state: SessionState,
) -> list[str]:
    if key in state:
        return column.multiselect(label, options, key=key)
    return column.multiselect(label, options, default=default, key=key)


def render_filter_bar(state: SessionState, options: DashboardFilterOptions) -> DashboardFilters:
    """Render all filters, store immutable selections, and support a clean reset."""
    current = _current(state)
    st.subheader("Filters")
    top = st.columns([3, 1])
    with top[1]:
        st.button(
            "Reset Filters",
            on_click=_reset_widgets,
            args=(state, options),
            width="stretch",
        )
    default_dates: list[date | datetime | str | None] = []
    if options.minimum_date is not None and options.maximum_date is not None:
        default_dates = [
            current.date_from or options.minimum_date,
            current.date_to or options.maximum_date,
        ]
    selected_dates: object
    if _WIDGET_KEYS["dates"] in state:
        selected_dates = top[0].date_input(
            "Date range",
            min_value=options.minimum_date,
            max_value=options.maximum_date,
            key=_WIDGET_KEYS["dates"],
        )
    else:
        selected_dates = top[0].date_input(
            "Date range",
            value=default_dates,
            min_value=options.minimum_date,
            max_value=options.maximum_date,
            key=_WIDGET_KEYS["dates"],
        )
    first_row = st.columns(4)
    countries = _multiselect(
        first_row[0],
        "Country",
        options.countries,
        _valid(current.countries, options.countries),
        _WIDGET_KEYS["countries"],
        state,
    )
    categories = _multiselect(
        first_row[1],
        "Product category",
        options.categories,
        _valid(current.categories, options.categories),
        _WIDGET_KEYS["categories"],
        state,
    )
    channels = _multiselect(
        first_row[2],
        "Sales channel",
        options.sales_channels,
        _valid(current.sales_channels, options.sales_channels),
        _WIDGET_KEYS["channels"],
        state,
    )
    warehouses = _multiselect(
        first_row[3],
        "Warehouse",
        options.warehouses,
        _valid(current.warehouses, options.warehouses),
        _WIDGET_KEYS["warehouses"],
        state,
    )
    second_row = st.columns(2)
    currencies = _multiselect(
        second_row[0],
        "Currency",
        options.currencies,
        _valid(current.currencies, options.currencies),
        _WIDGET_KEYS["currencies"],
        state,
    )
    statuses = _multiselect(
        second_row[1],
        "Order status",
        options.order_statuses,
        _valid(current.order_statuses, options.order_statuses),
        _WIDGET_KEYS["statuses"],
        state,
    )
    date_from, date_to = _date_range(selected_dates)
    if date_from == options.minimum_date and date_to == options.maximum_date:
        date_from = date_to = None
    selected = DashboardFilters(
        date_from=date_from,
        date_to=date_to,
        countries=tuple(countries),
        categories=tuple(categories),
        sales_channels=tuple(channels),
        warehouses=tuple(warehouses),
        currencies=tuple(currencies),
        order_statuses=tuple(statuses),
    )
    state[StateKey.ACTIVE_FILTERS.value] = selected
    st.caption(f"Active filters: {selected.active_count}")
    return selected
