"""Executive-summary worksheet builder."""

from dataclasses import asdict

import pandas as pd
from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.formatting import (
    write_dataframe_table,
    write_section_header,
    write_title,
)
from retailflow.reporting.worksheets import WorksheetContext


def write_summary_worksheet(worksheet: Worksheet, context: WorksheetContext) -> int:
    """Write headline KPIs, processing totals, and leading recommendations."""
    write_title(worksheet, "Executive Summary", context.formats)
    write_section_header(worksheet, 2, "Key Performance Indicators", context.formats)
    labels = {
        "gross_revenue": "Gross Revenue",
        "net_revenue": "Net Revenue",
        "gross_profit": "Gross Profit",
        "gross_margin_percent": "Gross Margin",
        "orders": "Completed Orders",
        "units_sold": "Units Sold",
        "average_order_value": "Average Order Value",
        "returned_quantity": "Returned Quantity",
        "refund_amount": "Refund Amount",
        "return_rate_percent": "Return Rate",
    }
    kpi_items = [
        (key, value) for key, value in asdict(context.sales.kpis).items() if key in labels
    ]
    kpi_frame = pd.DataFrame(
        [{"metric": labels[key], "value": value} for key, value in kpi_items]
    )
    next_row = write_dataframe_table(
        worksheet,
        kpi_frame,
        3,
        0,
        context.formats,
        "ExecutiveKPIs",
        freeze_at=(4, 0),
    )
    monetary_metrics = {
        "gross_revenue",
        "net_revenue",
        "gross_profit",
        "average_order_value",
        "refund_amount",
    }
    percentage_metrics = {"gross_margin_percent", "return_rate_percent"}
    for offset, (key, value) in enumerate(kpi_items, start=4):
        if key in monetary_metrics:
            value_format = context.formats.currency
        elif key in percentage_metrics:
            value_format = context.formats.percentage_points
        else:
            value_format = context.formats.integer
        worksheet.write(offset, 1, float(value), value_format)
    write_section_header(worksheet, next_row, "Processing Summary", context.formats)
    processing_frame = pd.DataFrame(
        [
            {
                "dataset": dataset_type.value,
                "source_rows": statistics.input_rows,
                "processed_rows": statistics.processed_rows,
                "excluded_rows": statistics.excluded_rows,
                "issues": statistics.issue_count,
            }
            for dataset_type, statistics in context.processing.statistics.by_dataset.items()
        ]
    )
    next_row = write_dataframe_table(
        worksheet,
        processing_frame,
        next_row + 1,
        0,
        context.formats,
        "ProcessingSummary",
        include_totals=True,
    )
    if not context.recommendations.empty:
        write_section_header(worksheet, next_row, "Priority Recommendations", context.formats)
        next_row = write_dataframe_table(
            worksheet,
            context.recommendations.head(10),
            next_row + 1,
            0,
            context.formats,
            "SummaryRecommendations",
        )
    worksheet.hide_gridlines(2)
    return next_row
