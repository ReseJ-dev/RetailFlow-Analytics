"""Product-performance worksheet builder."""

from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.formatting import (
    write_dataframe_table,
    write_section_header,
    write_title,
)
from retailflow.reporting.worksheets import WorksheetContext


def write_products_worksheet(worksheet: Worksheet, context: WorksheetContext) -> int:
    """Write category and top-product performance tables."""
    write_title(worksheet, "Product Performance", context.formats)
    next_row = 2
    for title, frame, table_name in (
        ("Category Performance", context.sales.category_performance, "CategoryPerformance"),
        (
            "Top Products by Revenue",
            context.sales.top_products_by_revenue,
            "TopProductsRevenue",
        ),
        (
            "Top Products by Gross Profit",
            context.sales.top_products_by_gross_profit,
            "TopProductsProfit",
        ),
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
            freeze_at=(4, 0) if next_row == 2 else None,
        )
    return next_row
