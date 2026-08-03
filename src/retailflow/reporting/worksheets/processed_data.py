"""Processed order-level data worksheet builder."""

from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.formatting import write_dataframe_table, write_title
from retailflow.reporting.worksheets import WorksheetContext


def write_processed_data_worksheet(worksheet: Worksheet, context: WorksheetContext) -> int:
    """Write the processed order-level fact table with traceability fields."""
    write_title(worksheet, "Processed Order Data", context.formats)
    return write_dataframe_table(
        worksheet,
        context.processing.processed_orders,
        2,
        0,
        context.formats,
        "ProcessedOrders",
        include_totals=True,
        freeze_at=(3, 0),
    )
