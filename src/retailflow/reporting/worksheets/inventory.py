"""Inventory worksheet builder."""

from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.formatting import write_dataframe_table, write_title
from retailflow.reporting.worksheets import WorksheetContext


def write_inventory_worksheet(worksheet: Worksheet, context: WorksheetContext) -> int:
    """Write inventory analytics or the processed inventory source data."""
    write_title(worksheet, "Inventory", context.formats)
    frame = (
        context.inventory_analytics
        if not context.inventory_analytics.empty
        else context.processing.inventory
    )
    next_row = write_dataframe_table(
        worksheet,
        frame,
        2,
        0,
        context.formats,
        "InventoryAnalysis",
        freeze_at=(3, 0),
    )
    if "inventory_status" in frame.columns and not frame.empty:
        status_column = list(frame.columns).index("inventory_status")
        first_row = 3
        last_row = 2 + len(frame)
        worksheet.conditional_format(
            first_row,
            status_column,
            last_row,
            status_column,
            {
                "type": "text",
                "criteria": "containing",
                "value": "Out of Stock",
                "format": context.formats.error,
            },
        )
        worksheet.conditional_format(
            first_row,
            status_column,
            last_row,
            status_column,
            {
                "type": "text",
                "criteria": "containing",
                "value": "Critical",
                "format": context.formats.warning,
            },
        )
    return next_row
