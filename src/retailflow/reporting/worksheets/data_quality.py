"""Data-quality worksheet builder."""

from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.formatting import (
    write_dataframe_table,
    write_section_header,
    write_title,
)
from retailflow.reporting.worksheets import WorksheetContext
from retailflow.validation.validation_result import issues_to_dataframe


def write_data_quality_worksheet(worksheet: Worksheet, context: WorksheetContext) -> int:
    """Write validation issues and excluded source rows."""
    write_title(worksheet, "Data Quality", context.formats)
    write_section_header(worksheet, 2, "Validation Issues", context.formats)
    issue_frame = issues_to_dataframe(context.processing.validation_issues)
    next_row = write_dataframe_table(
        worksheet,
        issue_frame,
        3,
        0,
        context.formats,
        "ValidationIssues",
        freeze_at=(4, 0),
    )
    if not issue_frame.empty:
        severity_column = list(issue_frame.columns).index("severity")
        worksheet.conditional_format(
            4,
            severity_column,
            3 + len(issue_frame),
            severity_column,
            {
                "type": "text",
                "criteria": "containing",
                "value": "error",
                "format": context.formats.error,
            },
        )
        worksheet.conditional_format(
            4,
            severity_column,
            3 + len(issue_frame),
            severity_column,
            {
                "type": "text",
                "criteria": "containing",
                "value": "warning",
                "format": context.formats.warning,
            },
        )
    write_section_header(worksheet, next_row, "Excluded Rows", context.formats)
    return write_dataframe_table(
        worksheet,
        context.processing.excluded_rows,
        next_row + 1,
        0,
        context.formats,
        "ExcludedRows",
    )
