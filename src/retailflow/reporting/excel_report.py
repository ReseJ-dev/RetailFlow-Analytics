"""Generate the initial multi-sheet Excel management report."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import uuid4

import pandas as pd
from xlsxwriter.exceptions import XlsxWriterException
from xlsxwriter.workbook import Workbook

from retailflow import __version__
from retailflow.analytics.comparisons import compare_periods
from retailflow.analytics.models import (
    PeriodComparison,
    ReturnsAnalyticsResult,
    SalesAnalyticsResult,
)
from retailflow.analytics.recommendations import Recommendation, recommendations_to_dataframe
from retailflow.common.exceptions import ReportGenerationError
from retailflow.models import ProcessingResult
from retailflow.reporting.formatting import (
    DEFAULT_THEME,
    ReportTheme,
    ReportVisualThresholds,
    create_report_formats,
)
from retailflow.reporting.worksheets import WorksheetContext
from retailflow.reporting.worksheets.cover import write_cover_worksheet
from retailflow.reporting.worksheets.data_quality import write_data_quality_worksheet
from retailflow.reporting.worksheets.inventory import write_inventory_worksheet
from retailflow.reporting.worksheets.metadata import write_metadata_worksheet
from retailflow.reporting.worksheets.processed_data import write_processed_data_worksheet
from retailflow.reporting.worksheets.products import write_products_worksheet
from retailflow.reporting.worksheets.returns import write_returns_worksheet
from retailflow.reporting.worksheets.sales import write_sales_worksheet
from retailflow.reporting.worksheets.summary import write_summary_worksheet

logger = logging.getLogger("retailflow.reporting")

REQUIRED_WORKSHEETS = (
    "00_Cover",
    "01_Executive_Summary",
    "02_Sales_Analysis",
    "03_Product_Performance",
    "04_Inventory",
    "05_Returns",
    "06_Data_Quality",
    "07_Processed_Data",
    "08_Report_Metadata",
)


@dataclass(frozen=True, slots=True)
class ReportGenerationStatistics:
    """Aggregate statistics describing one generated workbook."""

    worksheet_count: int
    processed_order_rows: int
    inventory_rows: int
    return_rows: int
    excluded_rows: int
    issue_count: int
    generation_seconds: float
    rows_by_worksheet: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReportGenerationResult:
    """Path, size, and generation statistics for an Excel report."""

    report_path: Path
    file_size: int
    statistics: ReportGenerationStatistics

    @property
    def path(self) -> Path:
        """Return the generated report path using a concise alias."""
        return self.report_path

    @property
    def size(self) -> int:
        """Return the generated report size in bytes."""
        return self.file_size


class ExcelReportGenerator:
    """Create a formatted management workbook from processed and analytical results."""

    def __init__(
        self,
        output_directory: str | Path = Path("output"),
        *,
        company_name: str = "RetailFlow Analytics",
        default_currency: str = "USD",
        overwrite: bool = False,
        theme: ReportTheme = DEFAULT_THEME,
    ) -> None:
        """Configure report identity, destination, currency, and overwrite behavior."""
        self.output_directory = Path(output_directory)
        self.company_name = company_name
        self.default_currency = default_currency.upper()
        self.overwrite = overwrite
        self.theme = theme

    def generate(
        self,
        processing_result: ProcessingResult,
        sales_analytics: SalesAnalyticsResult,
        returns_analytics: ReturnsAnalyticsResult,
        *,
        inventory_analytics: pd.DataFrame | None = None,
        recommendations: Iterable[Recommendation] = (),
        filename: str | None = None,
        report_id: str | None = None,
        generated_at: datetime | None = None,
        overwrite: bool | None = None,
        previous_sales_analytics: SalesAnalyticsResult | None = None,
        period_comparison: PeriodComparison | None = None,
        reporting_period: str | None = None,
        prepared_by: str = "RetailFlow Analytics",
        report_title: str = "RetailFlow Analytics Management Report",
        logo_path: str | Path | None = None,
        include_processed_data: bool = True,
        include_data_quality_report: bool = True,
        include_inventory_analysis: bool = True,
        include_returns_analysis: bool = True,
        include_recommendations: bool = True,
        visual_thresholds: ReportVisualThresholds | None = None,
    ) -> ReportGenerationResult:
        """Generate the workbook and return its path, size, and aggregate statistics."""
        started_at = monotonic()
        timestamp = generated_at or datetime.now(UTC)
        identifier = report_id or uuid4().hex
        report_filename = filename or f"retailflow_report_{timestamp:%Y%m%d_%H%M%S}.xlsx"
        if not report_filename.lower().endswith(".xlsx"):
            report_filename = f"{report_filename}.xlsx"
        target = self.output_directory / Path(report_filename).name
        allow_overwrite = self.overwrite if overwrite is None else overwrite

        try:
            self.output_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ReportGenerationError(
                f"The report output directory '{self.output_directory}' could not be created.",
                technical_detail=str(error),
            ) from error
        if target.exists() and not allow_overwrite:
            raise ReportGenerationError(
                "The report file already exists. Choose another filename or allow overwrite.",
                technical_detail=f"Existing report path: {target}",
            )

        temporary_path = target.with_name(f".{target.stem}.{identifier}.tmp")
        inventory_frame = inventory_analytics if inventory_analytics is not None else pd.DataFrame()
        recommendation_frame = (
            recommendations_to_dataframe(recommendations)
            if include_recommendations
            else pd.DataFrame()
        )
        resolved_logo = Path(logo_path) if logo_path is not None else None
        if resolved_logo is not None and not resolved_logo.is_file():
            raise ReportGenerationError(
                "The report logo file could not be found.",
                technical_detail=f"Missing logo path: {resolved_logo}",
            )
        resolved_period = reporting_period or _derive_reporting_period(sales_analytics)
        resolved_comparison = period_comparison
        if resolved_comparison is None and previous_sales_analytics is not None:
            resolved_comparison = compare_periods(
                sales_analytics.kpis, previous_sales_analytics.kpis
            )
        formats = None
        workbook: Workbook | None = None
        rows_by_worksheet: dict[str, int] = {}
        try:
            workbook = Workbook(
                temporary_path,
                {"nan_inf_to_errors": True, "remove_timezone": True},
            )
            formats = create_report_formats(workbook, self.default_currency, self.theme)
            included_worksheets = tuple(
                sheet_name
                for sheet_name in REQUIRED_WORKSHEETS
                if not (
                    (sheet_name == "04_Inventory" and not include_inventory_analysis)
                    or (sheet_name == "05_Returns" and not include_returns_analysis)
                    or (sheet_name == "06_Data_Quality" and not include_data_quality_report)
                    or (sheet_name == "07_Processed_Data" and not include_processed_data)
                )
            )
            context = WorksheetContext(
                processing=processing_result,
                sales=sales_analytics,
                returns=returns_analytics,
                inventory_analytics=inventory_frame,
                recommendations=recommendation_frame,
                formats=formats,
                company_name=self.company_name,
                default_currency=self.default_currency,
                report_id=identifier,
                generated_at=timestamp,
                application_version=__version__,
                reporting_period=resolved_period,
                prepared_by=prepared_by,
                report_title=report_title,
                included_worksheets=included_worksheets,
                logo_path=resolved_logo,
                previous_sales=previous_sales_analytics,
                period_comparison=resolved_comparison,
                visual_thresholds=visual_thresholds or ReportVisualThresholds(),
            )
            workbook.set_properties(
                {
                    "title": report_title,
                    "subject": "Sales, returns, inventory, and data-quality management report",
                    "author": self.company_name,
                    "company": self.company_name,
                    "comments": f"Report ID: {identifier}",
                }
            )
            sheet = workbook.add_worksheet("00_Cover")
            rows_by_worksheet["00_Cover"] = write_cover_worksheet(sheet, context)
            sheet = workbook.add_worksheet("01_Executive_Summary")
            rows_by_worksheet["01_Executive_Summary"] = write_summary_worksheet(
                workbook, sheet, context
            )
            sheet = workbook.add_worksheet("02_Sales_Analysis")
            rows_by_worksheet["02_Sales_Analysis"] = write_sales_worksheet(workbook, sheet, context)
            sheet = workbook.add_worksheet("03_Product_Performance")
            rows_by_worksheet["03_Product_Performance"] = write_products_worksheet(
                workbook, sheet, context
            )
            if include_inventory_analysis:
                sheet = workbook.add_worksheet("04_Inventory")
                rows_by_worksheet["04_Inventory"] = write_inventory_worksheet(
                    workbook, sheet, context
                )
            if include_returns_analysis:
                sheet = workbook.add_worksheet("05_Returns")
                rows_by_worksheet["05_Returns"] = write_returns_worksheet(
                    workbook, sheet, context
                )
            if include_data_quality_report:
                sheet = workbook.add_worksheet("06_Data_Quality")
                rows_by_worksheet["06_Data_Quality"] = write_data_quality_worksheet(
                    sheet, context
                )
            if include_processed_data:
                sheet = workbook.add_worksheet("07_Processed_Data")
                rows_by_worksheet["07_Processed_Data"] = write_processed_data_worksheet(
                    sheet, context
                )
            sheet = workbook.add_worksheet("08_Report_Metadata")
            rows_by_worksheet["08_Report_Metadata"] = write_metadata_worksheet(sheet, context)
            workbook.close()
            workbook = None
            temporary_path.replace(target)
        except MemoryError:
            if workbook is not None:
                with suppress(OSError, XlsxWriterException):
                    workbook.close()
            temporary_path.unlink(missing_ok=True)
            logger.exception("Excel report generation ran out of memory")
            raise
        except Exception as error:
            if workbook is not None:
                with suppress(OSError, XlsxWriterException):
                    workbook.close()
            temporary_path.unlink(missing_ok=True)
            logger.error("Excel report generation failed: %s", error)
            raise ReportGenerationError(
                "The Excel report could not be written. "
                "Close the workbook if it is open and try again.",
                technical_detail=str(error),
            ) from error

        elapsed = round(monotonic() - started_at, 3)
        statistics = ReportGenerationStatistics(
            worksheet_count=len(rows_by_worksheet),
            processed_order_rows=len(processing_result.processed_orders),
            inventory_rows=len(processing_result.inventory),
            return_rows=len(processing_result.returns),
            excluded_rows=len(processing_result.excluded_rows),
            issue_count=len(processing_result.validation_issues),
            generation_seconds=elapsed,
            rows_by_worksheet=rows_by_worksheet,
        )
        logger.info(
            "Generated Excel report with %d worksheets, %d processed rows, and %d issues",
            statistics.worksheet_count,
            statistics.processed_order_rows,
            statistics.issue_count,
        )
        return ReportGenerationResult(
            report_path=target.resolve(),
            file_size=target.stat().st_size,
            statistics=statistics,
        )


def generate_excel_report(
    processing_result: ProcessingResult,
    sales_analytics: SalesAnalyticsResult,
    returns_analytics: ReturnsAnalyticsResult,
    *,
    inventory_analytics: pd.DataFrame | None = None,
    recommendations: Iterable[Recommendation] = (),
    output_directory: str | Path = Path("output"),
    filename: str | None = None,
    company_name: str = "RetailFlow Analytics",
    default_currency: str = "USD",
    overwrite: bool = False,
    report_id: str | None = None,
    generated_at: datetime | None = None,
    previous_sales_analytics: SalesAnalyticsResult | None = None,
    period_comparison: PeriodComparison | None = None,
    reporting_period: str | None = None,
    prepared_by: str = "RetailFlow Analytics",
    report_title: str = "RetailFlow Analytics Management Report",
    logo_path: str | Path | None = None,
    include_processed_data: bool = True,
    include_data_quality_report: bool = True,
    include_inventory_analysis: bool = True,
    include_returns_analysis: bool = True,
    include_recommendations: bool = True,
    visual_thresholds: ReportVisualThresholds | None = None,
    theme: ReportTheme = DEFAULT_THEME,
) -> ReportGenerationResult:
    """Generate an Excel report through a convenient functional interface."""
    generator = ExcelReportGenerator(
        output_directory,
        company_name=company_name,
        default_currency=default_currency,
        overwrite=overwrite,
        theme=theme,
    )
    return generator.generate(
        processing_result,
        sales_analytics,
        returns_analytics,
        inventory_analytics=inventory_analytics,
        recommendations=recommendations,
        filename=filename,
        report_id=report_id,
        generated_at=generated_at,
        previous_sales_analytics=previous_sales_analytics,
        period_comparison=period_comparison,
        reporting_period=reporting_period,
        prepared_by=prepared_by,
        report_title=report_title,
        logo_path=logo_path,
        include_processed_data=include_processed_data,
        include_data_quality_report=include_data_quality_report,
        include_inventory_analysis=include_inventory_analysis,
        include_returns_analysis=include_returns_analysis,
        include_recommendations=include_recommendations,
        visual_thresholds=visual_thresholds,
    )


generate_report = generate_excel_report


def _derive_reporting_period(sales: SalesAnalyticsResult) -> str:
    """Derive a readable reporting period without changing analytical results."""
    if "order_date" not in sales.enriched_orders.columns or sales.enriched_orders.empty:
        return "No reporting period available"
    dates = pd.to_datetime(sales.enriched_orders["order_date"], errors="coerce").dropna()
    if dates.empty:
        return "No reporting period available"
    return f"{dates.min():%Y-%m-%d} to {dates.max():%Y-%m-%d}"
