"""Interactive Plotly charts for prepared dashboard datasets."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.services.dashboard_service import DashboardChartData

_COLOURS = ["#17365D", "#4472C4", "#70AD47", "#ED7D31", "#C00000", "#7F8C8D"]


def _empty(message: str) -> None:
    st.info(message)


def _money_axis(figure: go.Figure, currency: str, *, horizontal: bool = False) -> None:
    axis = {"tickformat": ",.2f", "ticksuffix": f" {currency}"}
    if horizontal:
        figure.update_xaxes(**axis)
    else:
        figure.update_yaxes(**axis)


def _show(figure: go.Figure) -> None:
    figure.update_layout(
        template="plotly_white",
        colorway=_COLOURS,
        margin={"l": 20, "r": 20, "t": 60, "b": 20},
        legend_title_text="",
    )
    st.plotly_chart(figure, width="stretch", config={"displaylogo": False})


def revenue_over_time(frame: pd.DataFrame, currency: str) -> None:
    if frame.empty:
        _empty("No revenue data is available for the selected filters.")
        return
    figure = px.line(
        frame,
        x="date",
        y="net_revenue",
        markers=True,
        title="Revenue over time",
        labels={"date": "Date", "net_revenue": f"Net revenue ({currency})"},
        hover_data=["orders", "units_sold"],
    )
    _money_axis(figure, currency)
    _show(figure)


def current_vs_previous(frame: pd.DataFrame, currency: str) -> None:
    if frame.empty:
        _empty("No current or previous-period revenue is available.")
        return
    long = frame.melt(
        id_vars="period_day",
        value_vars=["current_period", "previous_period"],
        var_name="period",
        value_name="net_revenue",
    ).dropna(subset=["net_revenue"])
    if long.empty:
        _empty("No current or previous-period revenue is available.")
        return
    figure = px.line(
        long,
        x="period_day",
        y="net_revenue",
        color="period",
        markers=True,
        title="Current vs previous period",
        labels={"period_day": "Day in period", "net_revenue": f"Net revenue ({currency})"},
    )
    _money_axis(figure, currency)
    _show(figure)


def _money_bar(
    frame: pd.DataFrame,
    *,
    category: str,
    value: str,
    title: str,
    category_label: str,
    currency: str,
    horizontal: bool = False,
) -> None:
    if frame.empty:
        _empty(f"No data is available for {title.lower()}.")
        return
    if horizontal:
        figure = px.bar(
            frame,
            x=value,
            y=category,
            orientation="h",
            title=title,
            labels={category: category_label, value: f"Amount ({currency})"},
            hover_data=[column for column in ("orders", "units_sold") if column in frame],
        )
    else:
        figure = px.bar(
            frame,
            x=category,
            y=value,
            title=title,
            labels={category: category_label, value: f"Amount ({currency})"},
            hover_data=[column for column in ("orders", "units_sold") if column in frame],
        )
    _money_axis(figure, currency, horizontal=horizontal)
    _show(figure)


def render_dashboard_charts(data: DashboardChartData, currency: str) -> None:
    """Render all eight interactive charts from service-prepared datasets."""
    first = st.columns(2)
    with first[0]:
        revenue_over_time(data.revenue_over_time, currency)
    with first[1]:
        current_vs_previous(data.current_vs_previous, currency)
    second = st.columns(2)
    with second[0]:
        _money_bar(
            data.revenue_by_category,
            category="category",
            value="net_revenue",
            title="Revenue by category",
            category_label="Category",
            currency=currency,
        )
    with second[1]:
        product_label = (
            "product_name" if "product_name" in data.top_products_by_profit else "product_id"
        )
        _money_bar(
            data.top_products_by_profit,
            category=product_label,
            value="gross_profit",
            title="Top ten products by gross profit",
            category_label="Product",
            currency=currency,
            horizontal=True,
        )
    third = st.columns(2)
    with third[0]:
        _money_bar(
            data.sales_by_country,
            category="country",
            value="net_revenue",
            title="Sales by country",
            category_label="Country",
            currency=currency,
            horizontal=True,
        )
    with third[1]:
        _money_bar(
            data.sales_by_channel,
            category="sales_channel",
            value="net_revenue",
            title="Sales-channel performance",
            category_label="Sales channel",
            currency=currency,
        )
    fourth = st.columns(2)
    with fourth[0]:
        if data.inventory_risk.empty:
            _empty("No inventory-risk data is available for the selected filters.")
        else:
            _show(
                px.pie(
                    data.inventory_risk,
                    names="inventory_status",
                    values="products",
                    hole=0.55,
                    title="Inventory-risk distribution",
                    hover_data=["products"],
                )
            )
    with fourth[1]:
        if data.return_reasons.empty:
            _empty("No returns were recorded for the selected filters.")
        else:
            figure = px.bar(
                data.return_reasons,
                x="return_reason",
                y="returned_quantity",
                title="Return reasons",
                labels={"return_reason": "Reason", "returned_quantity": "Returned units"},
                hover_data=["returns", "refund_amount"],
            )
            _show(figure)
