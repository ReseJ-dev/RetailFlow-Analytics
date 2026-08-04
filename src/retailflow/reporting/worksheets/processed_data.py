"""Processed order-level data worksheet builder."""

from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.formatting import (
    apply_worksheet_defaults,
    configure_print_layout,
    write_back_to_summary,
    write_dataframe_table,
    write_title,
)
from retailflow.reporting.worksheets import WorksheetContext


def write_processed_data_worksheet(worksheet: Worksheet, context: WorksheetContext) -> int:
    """Write the processed order-level fact table with traceability fields."""
    apply_worksheet_defaults(worksheet, context.formats)
    write_title(worksheet, "Processed Order Data", context.formats)
    write_back_to_summary(worksheet, context.formats)
    final_row = write_dataframe_table(
        worksheet,
        context.processing.processed_orders,
        2,
        0,
        context.formats,
        "ProcessedOrders",
        include_totals=True,
        freeze_at=(3, 0),
        empty_message="No processed order rows are available.",
    )
    configure_print_layout(
        worksheet,
        report_id=context.report_id,
        generated_at=context.generated_at,
        last_row=final_row,
        last_column=max(0, len(context.processing.processed_orders.columns) - 1),
        repeat_header_row=2,
    )
    return final_row
