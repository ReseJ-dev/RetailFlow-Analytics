from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from app.components import charts
from app.services.dashboard_service import DashboardChartData
from app.styles.plotly_theme import (
    CATEGORICAL_COLOURS,
    apply_chart_theme,
    create_empty_chart_state,
    format_currency_axis,
    format_percentage_axis,
    get_plotly_config,
)
from app.styles.tokens import DESIGN_TOKENS


class _Column(AbstractContextManager["_Column"]):
    def __exit__(self, *args: object) -> None:
        return None


def _chart_data(*, empty: bool = False) -> DashboardChartData:
    if empty:
        frames = [pd.DataFrame() for _ in range(8)]
        return DashboardChartData(*frames)
    return DashboardChartData(
        revenue_over_time=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
                "net_revenue": [125.5, 240.0],
                "orders": [2, 3],
                "units_sold": [3, 5],
            }
        ),
        current_vs_previous=pd.DataFrame(
            {
                "period_day": [1, 2],
                "current_period": [125.5, 240.0],
                "previous_period": [100.0, 210.0],
            }
        ),
        revenue_by_category=pd.DataFrame(
            {"category": ["Home"], "net_revenue": [365.5], "orders": [5]}
        ),
        top_products_by_profit=pd.DataFrame(
            {"product_name": ["Lamp"], "gross_profit": [95.0], "units_sold": [4]}
        ),
        sales_by_country=pd.DataFrame(
            {"country": ["France"], "net_revenue": [365.5], "orders": [5]}
        ),
        sales_by_channel=pd.DataFrame(
            {"sales_channel": ["Website"], "net_revenue": [365.5], "orders": [5]}
        ),
        inventory_risk=pd.DataFrame(
            {"inventory_status": ["Critical", "Healthy"], "products": [2, 8]}
        ),
        return_reasons=pd.DataFrame(
            {
                "return_reason": ["Damaged"],
                "returned_quantity": [1],
                "returns": [1],
                "refund_amount": [25.0],
            }
        ),
    )


def _capture_dashboard(
    monkeypatch: Any,
    data: DashboardChartData,
) -> list[tuple[go.Figure, dict[str, Any]]]:
    rendered: list[tuple[go.Figure, dict[str, Any]]] = []
    monkeypatch.setattr(charts.st, "columns", lambda count: [_Column() for _ in range(count)])
    monkeypatch.setattr(
        charts.st,
        "plotly_chart",
        lambda figure, **kwargs: rendered.append((figure, kwargs)),
    )
    charts.render_dashboard_charts(data, "EUR")
    return rendered


def test_theme_preserves_trace_values_and_removes_default_grey_background() -> None:
    figure = go.Figure(go.Scatter(x=[1, 2], y=[10.0, 20.0], name="Revenue"))
    original_x = tuple(figure.data[0].x)
    original_y = tuple(figure.data[0].y)

    result = apply_chart_theme(figure)

    assert result is figure
    assert tuple(figure.data[0].x) == original_x
    assert tuple(figure.data[0].y) == original_y
    assert figure.layout.paper_bgcolor == "rgba(0,0,0,0)"
    assert figure.layout.plot_bgcolor == DESIGN_TOKENS.colours.surface_background
    assert figure.layout.font.color == DESIGN_TOKENS.colours.primary_text
    assert figure.layout.xaxis.gridcolor == DESIGN_TOKENS.colours.border
    assert figure.data[0].line.color == CATEGORICAL_COLOURS[0]


def test_axis_helpers_format_currency_and_percentage_values() -> None:
    figure = go.Figure()

    format_currency_axis(figure, "eur", axis="x")
    format_percentage_axis(figure, axis="y")

    assert figure.layout.xaxis.tickformat == ",.2f"
    assert figure.layout.xaxis.ticksuffix == " EUR"
    assert figure.layout.yaxis.tickformat == ",.1f"
    assert figure.layout.yaxis.ticksuffix == "%"


def test_plotly_config_keeps_export_and_removes_secondary_selection_tools() -> None:
    config = get_plotly_config()
    removed = config["modeBarButtonsToRemove"]

    assert config["responsive"] is True
    assert config["displaylogo"] is False
    assert "select2d" in removed
    assert "lasso2d" in removed
    assert "toImage" not in removed
    assert config["toImageButtonOptions"] == {
        "format": "png",
        "filename": "retailflow-chart",
        "scale": 2,
    }


def test_empty_chart_state_escapes_dynamic_text() -> None:
    figure = create_empty_chart_state("No data for <script>alert(1)</script>", title="Revenue")

    assert not figure.data
    assert figure.layout.annotations[0].text == (
        "No data for &lt;script&gt;alert(1)&lt;/script&gt;"
    )
    assert figure.layout.xaxis.visible is False
    assert figure.layout.yaxis.visible is False


def test_all_dashboard_charts_share_theme_config_and_readable_hovers(monkeypatch: Any) -> None:
    rendered = _capture_dashboard(monkeypatch, _chart_data())

    assert len(rendered) == 8
    for figure, kwargs in rendered:
        assert figure.layout.paper_bgcolor == "rgba(0,0,0,0)"
        assert figure.layout.plot_bgcolor == DESIGN_TOKENS.colours.surface_background
        assert kwargs["config"] == get_plotly_config()
        assert kwargs["width"] == "stretch"

    comparison = rendered[1][0]
    assert [trace.name for trace in comparison.data] == ["Current period", "Previous period"]
    assert all("current_period" not in trace.hovertemplate for trace in comparison.data)
    assert tuple(rendered[0][0].data[0].y) == (125.5, 240.0)


def test_all_dashboard_charts_render_safe_empty_states(monkeypatch: Any) -> None:
    rendered = _capture_dashboard(monkeypatch, _chart_data(empty=True))

    assert len(rendered) == 8
    assert all(not figure.data for figure, _ in rendered)
    assert all(figure.layout.annotations for figure, _ in rendered)
