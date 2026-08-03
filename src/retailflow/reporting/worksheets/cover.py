"""Cover worksheet builder."""

from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.formatting import write_key_values, write_title
from retailflow.reporting.worksheets import WorksheetContext


def write_cover_worksheet(worksheet: Worksheet, context: WorksheetContext) -> int:
    """Write report identity and generation details."""
    write_title(worksheet, "RetailFlow Analytics Management Report", context.formats)
    worksheet.write(1, 0, "Decision-ready sales and inventory reporting", context.formats.subtitle)
    next_row = write_key_values(
        worksheet,
        [
            ("Company", context.company_name),
            ("Report ID", context.report_id),
            ("Generated", context.generated_at),
            ("Application Version", context.application_version),
            ("Reporting Currency", context.default_currency),
            ("Source Rows", context.processing.statistics.total_input_rows),
            ("Excluded Rows", context.processing.statistics.total_excluded_rows),
        ],
        3,
        context.formats,
    )
    worksheet.write(
        next_row + 1,
        0,
        "Use the numbered worksheets for executive KPIs, detailed analysis, data quality, "
        "processed records, and reproducibility metadata.",
        context.formats.note,
    )
    worksheet.set_column(0, 0, 28)
    worksheet.set_column(1, 1, 32)
    worksheet.set_column(2, 8, 14)
    worksheet.hide_gridlines(2)
    return next_row + 3
