"""Inventory worksheet builder."""

import pandas as pd
from xlsxwriter.workbook import Workbook
from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.chart_builder import add_doughnut_chart
from retailflow.reporting.formatting import (
    apply_worksheet_defaults,
    configure_print_layout,
    write_back_to_summary,
    write_dataframe_table,
    write_section_header,
    write_title,
)
from retailflow.reporting.worksheets import WorksheetContext


def write_inventory_worksheet(
    workbook: Workbook, worksheet: Worksheet, context: WorksheetContext
) -> int:
    """Write inventory analytics, status distribution, and exception highlights."""
    apply_worksheet_defaults(worksheet, context.formats)
    write_title(worksheet, "Inventory", context.formats)
    write_back_to_summary(worksheet, context.formats)
    frame = context.inventory_analytics
    if frame.empty and len(frame.columns) == 0:
        frame = context.processing.inventory
    next_row = write_dataframe_table(
        worksheet,
        frame,
        2,
        0,
        context.formats,
        "InventoryAnalysis",
        freeze_at=(3, 0),
        empty_message="No inventory records are available for the selected period.",
    )
    if "inventory_status" in frame.columns and not frame.empty:
        status_column = list(frame.columns).index("inventory_status")
        first, last = 3, 2 + len(frame)
        status_formats = {
            "Out of Stock": context.formats.error,
            "Critical": context.formats.error,
            "Low Stock": context.formats.warning,
            "Healthy": context.formats.success,
            "Overstock": context.formats.warning,
            "No Sales Data": context.formats.neutral,
        }
        for status, cell_format in status_formats.items():
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
        distribution = (
            frame["inventory_status"]
            .fillna("Unknown")
            .value_counts()
            .rename_axis("inventory_status")
            .reset_index(name="products")
        )
    else:
        distribution = pd.DataFrame(columns=["inventory_status", "products"])
    distribution_row = next_row
    write_section_header(
        worksheet, distribution_row, "Inventory Status Distribution", context.formats
    )
    end_row = write_dataframe_table(
        worksheet,
        distribution,
        distribution_row + 1,
        0,
        context.formats,
        "InventoryStatusDistribution",
        empty_message="No inventory status distribution is available.",
    )
    add_doughnut_chart(
        workbook,
        worksheet,
        sheet_name="04_Inventory",
        first_data_row=distribution_row + 2,
        last_data_row=distribution_row + 1 + len(distribution),
        category_column=0,
        value_column=1,
        title="Inventory Status Distribution",
        position=f"D{distribution_row + 2}",
        theme=context.formats.theme,
    )
    configure_print_layout(
        worksheet,
        report_id=context.report_id,
        generated_at=context.generated_at,
        last_row=max(end_row, distribution_row + 18),
        last_column=max(12, len(frame.columns) - 1),
        repeat_header_row=2,
    )
    return end_row
