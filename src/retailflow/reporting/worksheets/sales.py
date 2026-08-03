"""Sales-analysis worksheet builder."""

from xlsxwriter.workbook import Workbook
from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.chart_builder import add_column_chart
from retailflow.reporting.formatting import (
    write_dataframe_table,
    write_section_header,
    write_title,
)
from retailflow.reporting.worksheets import WorksheetContext


def write_sales_worksheet(
    workbook: Workbook,
    worksheet: Worksheet,
    context: WorksheetContext,
) -> int:
    """Write daily, weekly, country, and channel sales performance."""
    write_title(worksheet, "Sales Analysis", context.formats)
    write_section_header(worksheet, 2, "Daily Revenue", context.formats)
    daily_start = 3
    next_row = write_dataframe_table(
        worksheet,
        context.sales.daily_revenue,
        daily_start,
        0,
        context.formats,
        "DailyRevenue",
        include_totals=True,
        freeze_at=(4, 0),
    )
    daily_columns = [str(column) for column in context.sales.daily_revenue.columns]
    revenue_column = next(
        (index for index, name in enumerate(daily_columns) if "revenue" in name),
        None,
    )
    if revenue_column is not None and daily_columns:
        add_column_chart(
            workbook,
            worksheet,
            sheet_name="02_Sales_Analysis",
            first_data_row=daily_start + 1,
            last_data_row=daily_start + len(context.sales.daily_revenue),
            category_column=0,
            value_column=revenue_column,
            title="Daily Net Revenue",
            position="H3",
        )
    for title, frame, table_name in (
        ("Weekly Revenue", context.sales.weekly_revenue, "WeeklyRevenue"),
        ("Country Performance", context.sales.country_performance, "CountryPerformance"),
        ("Channel Performance", context.sales.channel_performance, "ChannelPerformance"),
    ):
        write_section_header(worksheet, next_row, title, context.formats)
        next_row = write_dataframe_table(
            worksheet,
            frame,
            next_row + 1,
            0,
            context.formats,
            table_name,
            include_totals=True,
        )
    return next_row
