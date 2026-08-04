"""Report metadata worksheet builder."""

import pandas as pd
from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.formatting import (
    apply_worksheet_defaults,
    configure_print_layout,
    write_back_to_summary,
    write_dataframe_table,
    write_key_values,
    write_section_header,
    write_title,
)
from retailflow.reporting.worksheets import WorksheetContext


def write_metadata_worksheet(worksheet: Worksheet, context: WorksheetContext) -> int:
    """Write reproducibility metadata and source-file characteristics."""
    apply_worksheet_defaults(worksheet, context.formats)
    write_title(worksheet, "Report Metadata", context.formats)
    write_back_to_summary(worksheet, context.formats)
    next_row = write_key_values(
        worksheet,
        [
            ("Report ID", context.report_id),
            ("Generated", context.generated_at),
            ("Application Version", context.application_version),
            ("Company", context.company_name),
            ("Reporting Period", context.reporting_period),
            ("Prepared By", context.prepared_by),
            ("Default Currency", context.default_currency),
            ("Total Source Rows", context.processing.statistics.total_input_rows),
            ("Total Processed Rows", context.processing.statistics.total_processed_rows),
            ("Total Excluded Rows", context.processing.statistics.total_excluded_rows),
            ("Validation Issues", len(context.processing.validation_issues)),
        ],
        2,
        context.formats,
    )
    write_section_header(worksheet, next_row + 1, "Source Files", context.formats)
    source_frame = pd.DataFrame(
        [
            {
                "dataset": dataset_type.value,
                "filename": metadata.filename,
                "file_type": metadata.file_type,
                "file_size": metadata.file_size,
                "row_count": metadata.row_count,
                "column_count": metadata.column_count,
                "selected_sheet_name": metadata.selected_sheet_name,
                "detected_delimiter": metadata.detected_delimiter,
                "detected_encoding": metadata.detected_encoding,
            }
            for dataset_type, metadata in context.processing.source_metadata.items()
        ]
    )
    final_row = write_dataframe_table(
        worksheet,
        source_frame,
        next_row + 2,
        0,
        context.formats,
        "ReportSources",
        include_totals=True,
        freeze_at=(3, 0),
        empty_message="No source-file metadata is available.",
    )
    configure_print_layout(
        worksheet,
        report_id=context.report_id,
        generated_at=context.generated_at,
        last_row=final_row,
        last_column=max(8, len(source_frame.columns) - 1),
    )
    return final_row
