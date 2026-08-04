"""Polished cover worksheet builder."""

from xlsxwriter.worksheet import Worksheet

from retailflow.reporting.formatting import (
    apply_worksheet_defaults,
    configure_print_layout,
    write_internal_link,
)
from retailflow.reporting.worksheets import WorksheetContext


def write_cover_worksheet(worksheet: Worksheet, context: WorksheetContext) -> int:
    """Write a print-ready report cover and navigation directory."""
    apply_worksheet_defaults(worksheet, context.formats)
    worksheet.merge_range(
        "A1:H2", context.report_title, context.formats.cover_title
    )
    worksheet.merge_range(
        "A3:H3",
        "Sales, inventory, returns, and data-quality review",
        context.formats.cover_subtitle,
    )
    details = (
        ("Company", context.company_name),
        ("Report ID", context.report_id),
        ("Reporting Period", context.reporting_period),
        ("Generated", context.generated_at),
        ("Prepared By", context.prepared_by),
        ("Application Version", context.application_version),
    )
    for row, (label, value) in enumerate(details, start=3):
        worksheet.write(row, 0, label, context.formats.label)
        value_format = context.formats.datetime if label == "Generated" else context.formats.text
        worksheet.merge_range(row, 1, row, 4, value, value_format)
    worksheet.merge_range(
        "A11:H12",
        "A decision-ready view of commercial performance, inventory exposure, returns, "
        "and source-data quality. Use the links below to move through the report.",
        context.formats.wrapped_text,
    )
    worksheet.write("A14", "Included sections", context.formats.section_header)
    sections = (
        ("01_Executive_Summary", "Executive Summary"),
        ("02_Sales_Analysis", "Sales Analysis"),
        ("03_Product_Performance", "Product Performance"),
        ("04_Inventory", "Inventory"),
        ("05_Returns", "Returns"),
        ("06_Data_Quality", "Data Quality"),
        ("07_Processed_Data", "Processed Data"),
        ("08_Report_Metadata", "Report Metadata"),
    )
    included_sections = (
        section for section in sections if section[0] in context.included_worksheets
    )
    for offset, (sheet_name, label) in enumerate(included_sections, start=15):
        write_internal_link(worksheet, f"A{offset}", sheet_name, f"› {label}", context.formats)
    write_internal_link(
        worksheet,
        "F14",
        "01_Executive_Summary",
        "Open Executive Summary",
        context.formats,
        button=True,
    )
    if context.logo_path is not None:
        worksheet.insert_image("F4", str(context.logo_path), {"x_scale": 0.45, "y_scale": 0.45})
    worksheet.set_column("A:A", 26)
    worksheet.set_column("B:E", 18)
    worksheet.set_column("F:H", 16)
    configure_print_layout(
        worksheet,
        report_id=context.report_id,
        generated_at=context.generated_at,
        last_row=23,
        last_column=7,
        landscape=False,
    )
    return 24
