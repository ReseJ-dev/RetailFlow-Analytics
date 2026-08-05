"""Interactive Plotly charts for prepared dashboard datasets."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.services.dashboard_service import DashboardChartData
from app.styles.plotly_theme import (
    apply_chart_theme,
    create_empty_chart_state,
    currency_hover_value,
    format_currency_axis,
    get_plotly_config,
)


def _empty(title: str, message: str) -> None:
    _show(create_empty_chart_state(message, title=title))


def _money_axis(figure: go.Figure, currency: str, *, horizontal: bool = False) -> None:
    format_currency_axis(figure, currency, axis="x" if horizontal else "y")


def _show(figure: go.Figure) -> None:
    apply_chart_theme(figure)
    st.plotly_chart(figure, width="stretch", config=get_plotly_config())


def revenue_over_time(frame: pd.DataFrame, currency: str) -> None:
    if frame.empty:
        _empty("Revenue over time", "No revenue data is available for the selected filters.")
        return
    figure = px.line(
        frame,
        x="date",
        y="net_revenue",
        markers=True,
        title="Revenue over time",
        labels={
            "date": "Date",
            "net_revenue": f"Net revenue ({currency})",
            "orders": "Orders",
            "units_sold": "Units sold",
        },
        hover_data=["orders", "units_sold"],
    )
    figure.update_traces(
        hovertemplate=(
            f"Date: %{{x|%d %b %Y}}<br>Net revenue: {currency_hover_value(currency)}"
            "<br>Orders: %{customdata[0]:,.0f}<br>Units sold: %{customdata[1]:,.0f}"
            "<extra></extra>"
        )
    )
    _money_axis(figure, currency)
    _show(figure)


def current_vs_previous(frame: pd.DataFrame, currency: str) -> None:
    if frame.empty:
        _empty(
            "Current vs previous period",
            "No current or previous-period revenue is available.",
        )
        return
    long = frame.melt(
        id_vars="period_day",
        value_vars=["current_period", "previous_period"],
        var_name="period",
        value_name="net_revenue",
    ).dropna(subset=["net_revenue"])
    if long.empty:
        _empty(
            "Current vs previous period",
            "No current or previous-period revenue is available.",
        )
        return
    figure = px.line(
        long,
        x="period_day",
        y="net_revenue",
        color="period",
        markers=True,
        title="Current vs previous period",
        labels={
            "period_day": "Day in period",
            "net_revenue": f"Net revenue ({currency})",
            "period": "Period",
        },
    )
    period_names = {
        "current_period": "Current period",
        "previous_period": "Previous period",
    }
    for trace in figure.data:
        display_name = period_names.get(str(trace.name), str(trace.name).replace("_", " ").title())
        trace.update(
            name=display_name,
            legendgroup=display_name,
            hovertemplate=(
                f"Day in period: %{{x}}<br>Net revenue: {currency_hover_value(currency)}"
                f"<extra>{display_name}</extra>"
            ),
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
        _empty(title, f"No data is available for {title.lower()}.")
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
    category_coordinate = "y" if horizontal else "x"
    money_hover = (
        currency_hover_value(currency, coordinate="x")
        if horizontal
        else currency_hover_value(currency)
    )
    hover_lines = [
        f"{category_label}: %{{{category_coordinate}}}",
        f"Amount: {money_hover}",
    ]
    custom_columns = [column for column in ("orders", "units_sold") if column in frame]
    for index, column in enumerate(custom_columns):
        label = "Orders" if column == "orders" else "Units sold"
        hover_lines.append(f"{label}: %{{customdata[{index}]:,.0f}}")
    figure.update_traces(hovertemplate="<br>".join(hover_lines) + "<extra></extra>")
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
            _empty(
                "Inventory-risk distribution",
                "No inventory-risk data is available for the selected filters.",
            )
        else:
            figure = px.pie(
                data.inventory_risk,
                names="inventory_status",
                values="products",
                hole=0.55,
                title="Inventory-risk distribution",
                labels={"inventory_status": "Inventory status", "products": "Products"},
            )
            figure.update_traces(
                hovertemplate=(
                    "Inventory status: %{label}<br>Products: %{value:,.0f}"
                    "<br>Share: %{percent:.1%}<extra></extra>"
                )
            )
            _show(figure)
    with fourth[1]:
        if data.return_reasons.empty:
            _empty("Return reasons", "No returns were recorded for the selected filters.")
        else:
            figure = px.bar(
                data.return_reasons,
                x="return_reason",
                y="returned_quantity",
                title="Return reasons",
                labels={
                    "return_reason": "Reason",
                    "returned_quantity": "Returned units",
                    "returns": "Returns",
                    "refund_amount": f"Refund amount ({currency})",
                },
                hover_data=["returns", "refund_amount"],
            )
            figure.update_traces(
                hovertemplate=(
                    "Reason: %{x}<br>Returned units: %{y:,.0f}"
                    "<br>Returns: %{customdata[0]:,.0f}"
                    "<br>Refund amount: "
                    f"{currency_hover_value(currency, coordinate='customdata[1]')}"
                    "<extra></extra>"
                )
            )
            _show(figure)
