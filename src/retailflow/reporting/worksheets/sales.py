"""Sales-analysis worksheet builder."""

import pandas as pd
from xlsxwriter.workbook import Workbook
from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.chart_builder import (
    ChartSeries,
    add_column_chart,
    add_horizontal_bar_chart,
    add_line_chart,
)
from retailflow.reporting.formatting import (
    apply_worksheet_defaults,
    configure_print_layout,
    write_back_to_summary,
    write_dataframe_table,
    write_section_header,
    write_title,
)
from retailflow.reporting.worksheets import WorksheetContext


def _with_previous(context: WorksheetContext) -> pd.DataFrame:
    frame = context.sales.daily_revenue.copy()
    if context.previous_sales is not None and not context.previous_sales.daily_revenue.empty:
        previous = context.previous_sales.daily_revenue["net_revenue"].reset_index(drop=True)
        frame = frame.reset_index(drop=True)
        frame["previous_period_revenue"] = previous.reindex(frame.index)
    return frame


def _value_column(frame: pd.DataFrame, name: str) -> int | None:
    return list(frame.columns).index(name) if name in frame else None


def write_sales_worksheet(
    workbook: Workbook, worksheet: Worksheet, context: WorksheetContext
) -> int:
    """Write detailed revenue trends and geographic/channel performance."""
    apply_worksheet_defaults(worksheet, context.formats)
    write_title(worksheet, "Sales Analysis", context.formats)
    write_back_to_summary(worksheet, context.formats)
    daily = _with_previous(context)
    write_section_header(worksheet, 2, "Daily Revenue", context.formats)
    daily_start = 3
    next_row = write_dataframe_table(
        worksheet,
        daily,
        daily_start,
        0,
        context.formats,
        "DailyRevenue",
        include_totals=True,
        freeze_at=(4, 0),
        empty_message="No sales were recorded during the selected period.",
    )
    series: list[ChartSeries] = []
    current_column = _value_column(daily, "net_revenue")
    if current_column is not None:
        series.append(ChartSeries("Current period", current_column))
    previous_column = _value_column(daily, "previous_period_revenue")
    if previous_column is not None:
        series.append(
            ChartSeries("Previous period", previous_column, context.formats.theme.neutral)
        )
    add_line_chart(
        workbook,
        worksheet,
        sheet_name="02_Sales_Analysis",
        first_data_row=daily_start + 1,
        last_data_row=daily_start + len(daily),
        category_column=0,
        series=series,
        title="Daily Net Revenue",
        position="P3",
        currency_axis=context.default_currency,
        theme=context.formats.theme,
    )
    next_row = max(next_row, 20)
    sections = (
        ("Weekly Revenue", context.sales.weekly_revenue, "WeeklyRevenue"),
        ("Country Performance", context.sales.country_performance, "CountryPerformance"),
        ("Channel Performance", context.sales.channel_performance, "ChannelPerformance"),
    )
    starts: dict[str, int] = {}
    for title, frame, table_name in sections:
        write_section_header(worksheet, next_row, title, context.formats)
        starts[table_name] = next_row + 1
        next_row = write_dataframe_table(
            worksheet, frame, next_row + 1, 0, context.formats, table_name, include_totals=True
        )
    country = context.sales.country_performance
    country_column = _value_column(country, "net_revenue")
    if country_column is not None:
        add_horizontal_bar_chart(
            workbook,
            worksheet,
            sheet_name="02_Sales_Analysis",
            first_data_row=starts["CountryPerformance"] + 1,
            last_data_row=starts["CountryPerformance"] + len(country),
            category_column=0,
            value_column=country_column,
            title="Revenue by Country",
            position="P22",
            currency_axis=context.default_currency,
            theme=context.formats.theme,
        )
    channel = context.sales.channel_performance
    channel_column = _value_column(channel, "net_revenue")
    if channel_column is not None:
        add_column_chart(
            workbook,
            worksheet,
            sheet_name="02_Sales_Analysis",
            first_data_row=starts["ChannelPerformance"] + 1,
            last_data_row=starts["ChannelPerformance"] + len(channel),
            category_column=0,
            value_column=channel_column,
            title="Revenue by Sales Channel",
            position="P40",
            currency_axis=context.default_currency,
            theme=context.formats.theme,
        )
    configure_print_layout(
        worksheet,
        report_id=context.report_id,
        generated_at=context.generated_at,
        last_row=next_row,
        last_column=max(15, len(daily.columns) - 1),
        repeat_header_row=3,
    )
    return next_row
