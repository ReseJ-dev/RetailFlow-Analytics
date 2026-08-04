"""Product-performance worksheet builder."""

import pandas as pd
from xlsxwriter.workbook import Workbook
from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.chart_builder import add_column_chart, add_horizontal_bar_chart
from retailflow.reporting.formatting import (
    apply_worksheet_defaults,
    configure_print_layout,
    write_back_to_summary,
    write_dataframe_table,
    write_section_header,
    write_title,
)
from retailflow.reporting.worksheets import WorksheetContext


def _apply_product_conditions(
    worksheet: Worksheet, frame: pd.DataFrame, start_row: int, context: WorksheetContext
) -> None:
    if frame.empty:
        return
    first, last = start_row + 1, start_row + len(frame)
    for name, criteria, value, cell_format in (
        ("gross_profit", "<", 0, context.formats.error),
        ("gross_profit", ">", 0, context.formats.success),
        (
            "gross_margin_percent",
            "<",
            context.visual_thresholds.low_gross_margin_percent,
            context.formats.warning,
        ),
        (
            "return_rate_percent",
            ">",
            context.visual_thresholds.high_return_rate_percent,
            context.formats.error,
        ),
    ):
        if name in frame:
            column = list(frame.columns).index(name)
            worksheet.conditional_format(
                first,
                column,
                last,
                column,
                {"type": "cell", "criteria": criteria, "value": value, "format": cell_format},
            )
    if "inventory_status" in frame:
        status_column = list(frame.columns).index("inventory_status")
        for status, cell_format in (
            ("Out of Stock", context.formats.error),
            ("Critical", context.formats.error),
            ("Low Stock", context.formats.warning),
            ("Healthy", context.formats.success),
            ("Overstock", context.formats.warning),
            ("No Sales Data", context.formats.neutral),
        ):
            worksheet.conditional_format(
                first,
                status_column,
                last,
                status_column,
                {
                    "type": "text",
                    "criteria": "containing",
                    "value": status,
                    "format": cell_format,
                },
            )


def write_products_worksheet(
    workbook: Workbook, worksheet: Worksheet, context: WorksheetContext
) -> int:
    """Write category and ranked product performance with visual exceptions."""
    apply_worksheet_defaults(worksheet, context.formats)
    write_title(worksheet, "Product Performance", context.formats)
    write_back_to_summary(worksheet, context.formats)
    next_row = 2
    sections = (
        ("Category Performance", context.sales.category_performance, "CategoryPerformance"),
        ("Top Products by Revenue", context.sales.top_products_by_revenue, "TopProductsRevenue"),
        (
            "Top Products by Gross Profit",
            context.sales.top_products_by_gross_profit,
            "TopProductsProfit",
        ),
        (
            "Product Inventory and Return Indicators",
            context.inventory_analytics,
            "ProductIndicators",
        ),
    )
    starts: dict[str, int] = {}
    for title, frame, table_name in sections:
        write_section_header(worksheet, next_row, title, context.formats)
        starts[table_name] = next_row + 1
        next_row = write_dataframe_table(
            worksheet,
            frame,
            next_row + 1,
            0,
            context.formats,
            table_name,
            include_totals=table_name != "ProductIndicators",
            freeze_at=(4, 0) if table_name == "CategoryPerformance" else None,
        )
        _apply_product_conditions(worksheet, frame, starts[table_name], context)
    category = context.sales.category_performance
    if not category.empty and "net_revenue" in category:
        add_column_chart(
            workbook,
            worksheet,
            sheet_name="03_Product_Performance",
            first_data_row=starts["CategoryPerformance"] + 1,
            last_data_row=starts["CategoryPerformance"] + len(category),
            category_column=0,
            value_column=list(category.columns).index("net_revenue"),
            title="Revenue by Category",
            position="P3",
            currency_axis=context.default_currency,
            theme=context.formats.theme,
        )
    profit = context.sales.top_products_by_gross_profit.head(10)
    if not profit.empty and "gross_profit" in profit:
        add_horizontal_bar_chart(
            workbook,
            worksheet,
            sheet_name="03_Product_Performance",
            first_data_row=starts["TopProductsProfit"] + 1,
            last_data_row=starts["TopProductsProfit"] + len(profit),
            category_column=1 if "product_name" in profit else 0,
            value_column=list(profit.columns).index("gross_profit"),
            title="Top 10 Products by Gross Profit",
            position="P22",
            currency_axis=context.default_currency,
            theme=context.formats.theme,
        )
    configure_print_layout(
        worksheet,
        report_id=context.report_id,
        generated_at=context.generated_at,
        last_row=next_row,
        last_column=20,
        repeat_header_row=3,
    )
    return next_row
