"""Excel management-report generation interfaces."""

from retailflow.reporting.excel_report import (
    ExcelReportGenerator,
    ReportGenerationResult,
    ReportGenerationStatistics,
    generate_excel_report,
)

__all__ = [
    "ExcelReportGenerator",
    "ReportGenerationResult",
    "ReportGenerationStatistics",
    "generate_excel_report",
]
