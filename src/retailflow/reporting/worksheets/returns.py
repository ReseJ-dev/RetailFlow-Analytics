"""Returns-analysis worksheet builder."""

from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.formatting import (
    write_dataframe_table,
    write_section_header,
    write_title,
)
from retailflow.reporting.worksheets import WorksheetContext


def write_returns_worksheet(worksheet: Worksheet, context: WorksheetContext) -> int:
    """Write return reasons and product return-rate analysis."""
    write_title(worksheet, "Returns", context.formats)
    write_section_header(worksheet, 2, "Return Reasons", context.formats)
    next_row = write_dataframe_table(
        worksheet,
        context.returns.return_reasons,
        3,
        0,
        context.formats,
        "ReturnReasons",
        include_totals=True,
        freeze_at=(4, 0),
    )
    write_section_header(worksheet, next_row, "Products by Return Rate", context.formats)
    return write_dataframe_table(
        worksheet,
        context.returns.products_by_return_rate,
        next_row + 1,
        0,
        context.formats,
        "ProductReturnRates",
        include_totals=True,
    )
