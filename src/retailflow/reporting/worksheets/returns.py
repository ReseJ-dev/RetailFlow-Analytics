"""Returns-analysis worksheet builder."""

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


def write_returns_worksheet(
    workbook: Workbook, worksheet: Worksheet, context: WorksheetContext
) -> int:
    """Write return reasons and highest product return rates."""
    apply_worksheet_defaults(worksheet, context.formats)
    write_title(worksheet, "Returns", context.formats)
    write_back_to_summary(worksheet, context.formats)
    reasons = context.returns.return_reasons
    write_section_header(worksheet, 2, "Return Reasons", context.formats)
    next_row = write_dataframe_table(
        worksheet,
        reasons,
        3,
        0,
        context.formats,
        "ReturnReasons",
        include_totals=True,
        freeze_at=(4, 0),
        empty_message="No returns were recorded during the selected period.",
    )
    if not reasons.empty and "returned_quantity" in reasons:
        add_doughnut_chart(
            workbook,
            worksheet,
            sheet_name="05_Returns",
            first_data_row=4,
            last_data_row=3 + len(reasons),
            category_column=0,
            value_column=list(reasons.columns).index("returned_quantity"),
            title="Return Reasons",
            position="F3",
            theme=context.formats.theme,
        )
    next_row = max(next_row, 21)
    products = context.returns.products_by_return_rate
    write_section_header(worksheet, next_row, "Products by Return Rate", context.formats)
    start = next_row + 1
    next_row = write_dataframe_table(
        worksheet,
        products,
        start,
        0,
        context.formats,
        "ProductReturnRates",
        include_totals=True,
        empty_message="No product return-rate data is available.",
    )
    if not products.empty and "return_rate_percent" in products:
        column = list(products.columns).index("return_rate_percent")
        worksheet.conditional_format(
            start + 1,
            column,
            start + len(products),
            column,
            {
                "type": "cell",
                "criteria": ">",
                "value": context.visual_thresholds.high_return_rate_percent,
                "format": context.formats.error,
            },
        )
    configure_print_layout(
        worksheet,
        report_id=context.report_id,
        generated_at=context.generated_at,
        last_row=next_row,
        last_column=12,
        repeat_header_row=3,
    )
    return next_row
