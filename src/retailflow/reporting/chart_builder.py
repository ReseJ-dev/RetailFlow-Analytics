"""Theme-aware chart builders that never emit blank chart objects."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from xlsxwriter.chart import Chart
from xlsxwriter.workbook import Workbook
from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.formatting import DEFAULT_THEME, ReportTheme


@dataclass(frozen=True, slots=True)
class ChartSeries:
    """One chart series referencing a worksheet column."""

    name: str
    value_column: int
    color: str | None = None


def _finish_chart(
    chart: Chart,
    worksheet: Worksheet,
    *,
    title: str,
    position: str,
    show_legend: bool,
    currency_axis: bool | str,
    x_scale: float = 1.25,
    y_scale: float = 1.1,
    theme: ReportTheme = DEFAULT_THEME,
) -> None:
    chart.set_title({"name": title, "name_font": {"name": theme.font_name, "size": 12}})
    chart.set_chartarea({"border": {"none": True}, "fill": {"color": theme.white}})
    chart.set_plotarea({"border": {"none": True}, "fill": {"color": theme.white}})
    chart.set_legend({"position": "bottom"} if show_legend else {"none": True})
    chart.set_y_axis(
        {
            "major_gridlines": {"visible": True, "line": {"color": "#D9E1F2"}},
            "num_format": (
                f'#,##0 "{currency_axis}"'
                if isinstance(currency_axis, str)
                else ("#,##0" if currency_axis else '#,##0""')
            ),
            "name_font": {"name": theme.font_name},
            "num_font": {"name": theme.font_name},
        }
    )
    chart.set_x_axis(
        {
            "name_font": {"name": theme.font_name},
            "num_font": {"name": theme.font_name},
        }
    )
    worksheet.insert_chart(position, chart, {"x_scale": x_scale, "y_scale": y_scale})


def add_line_chart(
    workbook: Workbook,
    worksheet: Worksheet,
    *,
    sheet_name: str,
    first_data_row: int,
    last_data_row: int,
    category_column: int,
    series: Sequence[ChartSeries],
    title: str,
    position: str,
    currency_axis: bool | str = False,
    theme: ReportTheme = DEFAULT_THEME,
) -> bool:
    """Add a line chart for one or more non-empty series."""
    if last_data_row < first_data_row or not series:
        return False
    chart = workbook.add_chart({"type": "line"})
    palette = (theme.accent, theme.warning, theme.positive, theme.neutral)
    for index, item in enumerate(series):
        chart.add_series(
            {
                "name": item.name,
                "categories": [
                    sheet_name,
                    first_data_row,
                    category_column,
                    last_data_row,
                    category_column,
                ],
                "values": [
                    sheet_name,
                    first_data_row,
                    item.value_column,
                    last_data_row,
                    item.value_column,
                ],
                "line": {"color": item.color or palette[index % len(palette)], "width": 2.25},
                "marker": {"type": "circle", "size": 4},
            }
        )
    _finish_chart(
        chart,
        worksheet,
        title=title,
        position=position,
        show_legend=len(series) > 1,
        currency_axis=currency_axis,
        theme=theme,
    )
    return True


def add_column_chart(
    workbook: Workbook,
    worksheet: Worksheet,
    *,
    sheet_name: str,
    first_data_row: int,
    last_data_row: int,
    category_column: int,
    value_column: int,
    title: str,
    position: str,
    currency_axis: bool | str = False,
    theme: ReportTheme = DEFAULT_THEME,
) -> bool:
    """Add a themed vertical column chart when source rows exist."""
    if last_data_row < first_data_row:
        return False
    chart = workbook.add_chart({"type": "column"})
    chart.add_series(
        {
            "name": title,
            "categories": [
                sheet_name,
                first_data_row,
                category_column,
                last_data_row,
                category_column,
            ],
            "values": [sheet_name, first_data_row, value_column, last_data_row, value_column],
            "fill": {"color": theme.accent},
            "border": {"none": True},
        }
    )
    _finish_chart(
        chart,
        worksheet,
        title=title,
        position=position,
        show_legend=False,
        currency_axis=currency_axis,
        theme=theme,
    )
    return True


def add_horizontal_bar_chart(
    workbook: Workbook,
    worksheet: Worksheet,
    *,
    sheet_name: str,
    first_data_row: int,
    last_data_row: int,
    category_column: int,
    value_column: int,
    title: str,
    position: str,
    currency_axis: bool | str = False,
    theme: ReportTheme = DEFAULT_THEME,
) -> bool:
    """Add a horizontal bar chart suited to ranked categories."""
    if last_data_row < first_data_row:
        return False
    chart = workbook.add_chart({"type": "bar"})
    chart.add_series(
        {
            "name": title,
            "categories": [
                sheet_name,
                first_data_row,
                category_column,
                last_data_row,
                category_column,
            ],
            "values": [sheet_name, first_data_row, value_column, last_data_row, value_column],
            "fill": {"color": theme.accent},
            "border": {"none": True},
        }
    )
    _finish_chart(
        chart,
        worksheet,
        title=title,
        position=position,
        show_legend=False,
        currency_axis=currency_axis,
        theme=theme,
    )
    if currency_axis:
        number_format = f'#,##0 "{currency_axis}"' if isinstance(currency_axis, str) else "#,##0"
        chart.set_x_axis(
            {
                "major_gridlines": {"visible": True, "line": {"color": "#D9E1F2"}},
                "num_format": number_format,
            }
        )
    chart.set_y_axis({"reverse": True})
    return True


def add_doughnut_chart(
    workbook: Workbook,
    worksheet: Worksheet,
    *,
    sheet_name: str,
    first_data_row: int,
    last_data_row: int,
    category_column: int,
    value_column: int,
    title: str,
    position: str,
    theme: ReportTheme = DEFAULT_THEME,
) -> bool:
    """Add a doughnut chart only when at least one category exists."""
    if last_data_row < first_data_row:
        return False
    chart = workbook.add_chart({"type": "doughnut"})
    chart.add_series(
        {
            "name": title,
            "categories": [
                sheet_name,
                first_data_row,
                category_column,
                last_data_row,
                category_column,
            ],
            "values": [sheet_name, first_data_row, value_column, last_data_row, value_column],
            "points": [
                {"fill": {"color": color}}
                for color in (
                    theme.error,
                    theme.warning,
                    theme.accent,
                    theme.positive,
                    theme.neutral,
                    theme.primary,
                )
            ],
            "data_labels": {"percentage": True, "leader_lines": True},
        }
    )
    chart.set_hole_size(55)
    chart.set_title({"name": title})
    chart.set_legend({"position": "bottom"})
    chart.set_chartarea({"border": {"none": True}})
    worksheet.insert_chart(position, chart, {"x_scale": 1.1, "y_scale": 1.1})
    return True
