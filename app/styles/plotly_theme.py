"""Shared Plotly presentation helpers for RetailFlow charts."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Literal

import plotly.graph_objects as go

from app.styles.tokens import DESIGN_TOKENS

AxisName = Literal["x", "y"]
HoverCoordinate = Literal["x", "y", "customdata[0]", "customdata[1]"]


@dataclass(frozen=True, slots=True)
class PlotlySemanticColours:
    """Named chart colours for states that carry business meaning."""

    positive: str = DESIGN_TOKENS.colours.success
    negative: str = DESIGN_TOKENS.colours.error
    neutral: str = DESIGN_TOKENS.colours.secondary_text
    warning: str = DESIGN_TOKENS.colours.warning
    information: str = DESIGN_TOKENS.colours.information


SEMANTIC_COLOURS = PlotlySemanticColours()

# This colour-blind-conscious sequence varies hue as well as lightness. Semantic
# red and green remain available for states, but are never the sole distinction
# between ordinary data series.
CATEGORICAL_COLOURS: tuple[str, ...] = (
    DESIGN_TOKENS.colours.primary,
    "#0891B2",
    DESIGN_TOKENS.colours.warning,
    "#7C3AED",
    "#DB2777",
    "#0F766E",
    DESIGN_TOKENS.colours.information,
    "#475467",
)


def _apply_trace_colours(figure: go.Figure) -> None:
    """Apply the categorical sequence without changing trace data."""
    for index, trace in enumerate(figure.data):
        colour = CATEGORICAL_COLOURS[index % len(CATEGORICAL_COLOURS)]
        if trace.type == "pie":
            labels = getattr(trace, "labels", None)
            count = len(labels) if labels is not None else len(CATEGORICAL_COLOURS)
            trace.update(
                marker_colors=[
                    CATEGORICAL_COLOURS[item % len(CATEGORICAL_COLOURS)]
                    for item in range(count)
                ]
            )
        elif trace.type == "bar":
            trace.update(marker_color=colour)
        elif trace.type in {"scatter", "scattergl"}:
            trace.update(line_color=colour, marker_color=colour)


def apply_chart_theme(figure: go.Figure) -> go.Figure:
    """Apply the RetailFlow Plotly theme in place and return ``figure``."""
    colours = DESIGN_TOKENS.colours
    typography = DESIGN_TOKENS.typography
    _apply_trace_colours(figure)
    figure.update_layout(
        template="none",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=colours.surface_background,
        colorway=CATEGORICAL_COLOURS,
        font={
            "family": typography.font_family,
            "size": 13,
            "color": colours.primary_text,
        },
        title={
            "font": {"size": 17, "color": colours.primary_text},
            "x": 0,
            "xanchor": "left",
            "yanchor": "top",
            "automargin": True,
            "pad": {"b": 8},
        },
        autosize=True,
        margin={"l": 48, "r": 16, "t": 60, "b": 48, "autoexpand": True},
        legend={
            "title": {"text": ""},
            "orientation": "h",
            "x": 0,
            "xanchor": "left",
            "y": -0.18,
            "yanchor": "top",
            "bgcolor": "rgba(0,0,0,0)",
            "font": {"size": 11, "color": colours.secondary_text},
            "itemwidth": 30,
        },
        hoverlabel={
            "bgcolor": colours.primary_text,
            "bordercolor": colours.primary_text,
            "font": {
                "family": typography.font_family,
                "size": 12,
                "color": colours.surface_background,
            },
            "align": "left",
        },
        hovermode="closest",
        separators=".,",
    )
    axis_style = {
        "showgrid": True,
        "gridcolor": colours.border,
        "gridwidth": 1,
        "zeroline": False,
        "linecolor": colours.border,
        "tickfont": {"size": 12, "color": colours.secondary_text},
        "title_font": {"size": 13, "color": colours.secondary_text},
        "title_standoff": 12,
        "automargin": True,
    }
    figure.update_xaxes(**axis_style)
    figure.update_yaxes(**axis_style)
    return figure


def get_plotly_config() -> dict[str, object]:
    """Return a fresh responsive mode-bar configuration for Streamlit charts."""
    return {
        "responsive": True,
        "displaylogo": False,
        "displayModeBar": "hover",
        "scrollZoom": False,
        "showTips": False,
        "doubleClick": "reset+autosize",
        "modeBarButtonsToRemove": [
            "select2d",
            "lasso2d",
            "autoScale2d",
            "toggleSpikelines",
            "hoverClosestCartesian",
            "hoverCompareCartesian",
        ],
        "toImageButtonOptions": {
            "format": "png",
            "filename": "retailflow-chart",
            "scale": 2,
        },
    }


def format_currency_axis(
    figure: go.Figure,
    currency: str,
    *,
    axis: AxisName = "y",
    decimals: int = 2,
) -> go.Figure:
    """Format one numeric axis as a monetary value with a currency suffix."""
    currency_label = " ".join(currency.upper().split())
    properties = {
        "tickformat": f",.{max(0, decimals)}f",
        "ticksuffix": f" {currency_label}" if currency_label else "",
        "hoverformat": f",.{max(0, decimals)}f",
    }
    if axis == "x":
        figure.update_xaxes(**properties)
    else:
        figure.update_yaxes(**properties)
    return figure


def format_percentage_axis(
    figure: go.Figure,
    *,
    axis: AxisName = "y",
    decimals: int = 1,
    values_are_fractions: bool = False,
) -> go.Figure:
    """Format one axis for percentage points or fractional percentage values."""
    places = max(0, decimals)
    properties = {
        "tickformat": f".{places}%" if values_are_fractions else f",.{places}f",
        "ticksuffix": "" if values_are_fractions else "%",
        "hoverformat": f".{places}%" if values_are_fractions else f",.{places}f",
    }
    if axis == "x":
        figure.update_xaxes(**properties)
    else:
        figure.update_yaxes(**properties)
    return figure


def currency_hover_value(currency: str, *, coordinate: HoverCoordinate = "y") -> str:
    """Return a Plotly hover placeholder for a safely labelled money value."""
    currency_label = escape(" ".join(currency.upper().split()))
    suffix = f" {currency_label}" if currency_label else ""
    return f"%{{{coordinate}:,.2f}}{suffix}"


def create_empty_chart_state(message: str, *, title: str | None = None) -> go.Figure:
    """Create a themed, non-interactive-looking empty chart with safe text."""
    figure = go.Figure()
    if title:
        figure.update_layout(title_text=escape(title))
    apply_chart_theme(figure)
    figure.add_annotation(
        text=escape(message),
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        align="center",
        font={"size": 13, "color": DESIGN_TOKENS.colours.secondary_text},
    )
    figure.update_layout(height=300)
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return figure


__all__ = [
    "CATEGORICAL_COLOURS",
    "SEMANTIC_COLOURS",
    "PlotlySemanticColours",
    "apply_chart_theme",
    "create_empty_chart_state",
    "currency_hover_value",
    "format_currency_axis",
    "format_percentage_axis",
    "get_plotly_config",
]
