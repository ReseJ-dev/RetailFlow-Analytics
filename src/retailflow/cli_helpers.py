"""CLI orchestration helpers built on RetailFlow's existing core modules."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import IntEnum
from pathlib import Path
from time import monotonic

import pandas as pd

from retailflow import __version__
from retailflow.analytics import (
    AnalyticsFilters,
    Recommendation,
    ReturnsAnalyticsResult,
    SalesAnalyticsResult,
    calculate_inventory_metrics,
    calculate_returns_analytics,
    calculate_sales_analytics,
    generate_recommendations,
)
from retailflow.common.config import RetailFlowSettings
from retailflow.common.exceptions import (
    ConfigurationError,
    DataSourceError,
    DataValidationError,
    ReportGenerationError,
    RetailFlowError,
)
from retailflow.ingestion import LoadedDataset, load_file
from retailflow.models import ProcessingProgress, ProcessingResult
from retailflow.pipeline import DataProcessingPipeline
from retailflow.reporting.excel_report import ExcelReportGenerator, ReportGenerationResult
from retailflow.storage import (
    RunRecord,
    RunRepository,
)
from retailflow.storage import (
    create_run_repository as open_run_repository,
)
from retailflow.storage.mappers import sanitize_configuration
from retailflow.validation import (
    CombinedValidationResult,
    DatasetType,
    DatasetValidationResult,
    ValidationSeverity,
    issues_to_dataframe,
)


class ExitCode(IntEnum):
    """Stable process exit codes exposed by every CLI command."""

    SUCCESS = 0
    CONFIGURATION_ERROR = 2
    SOURCE_FILE_ERROR = 3
    VALIDATION_FAILURE = 4
    REPORT_GENERATION_FAILURE = 5
    INTERNAL_ERROR = 10


class CliValidationError(DataValidationError):
    """Raised when processed source quality forbids CLI continuation."""


@dataclass(frozen=True, slots=True)
class SourcePaths:
    """Resolved required and optional CLI source paths."""

    orders: Path
    products: Path
    inventory: Path
    returns: Path
    targets: Path | None = None


@dataclass(frozen=True, slots=True)
class ReportingPeriod:
    """Inclusive analytics period."""

    start: date
    end: date

    @property
    def label(self) -> str:
        """Return a stable report label."""
        return f"{self.start:%Y-%m-%d} to {self.end:%Y-%m-%d}"


@dataclass(frozen=True, slots=True)
class AnalyticsBundle:
    """All analytical inputs consumed by the shared Excel generator."""

    sales: SalesAnalyticsResult
    returns: ReturnsAnalyticsResult
    inventory: pd.DataFrame
    recommendations: tuple[Recommendation, ...]


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    """Concise validation output safe for terminal display."""

    source_rows: int
    processed_rows: int
    excluded_rows: int
    warnings: int
    errors: int
    quality_score: float


@dataclass(frozen=True, slots=True)
class CliGenerationResult:
    """Generated report plus its persisted readable run ID."""

    report: ReportGenerationResult
    run_id: str
    validation: ValidationSummary


type StageCallback = Callable[[str], None]

logger = logging.getLogger("retailflow.cli")


def resolve_source_paths(
    settings: RetailFlowSettings,
    *,
    orders: Path | None,
    products: Path | None,
    inventory: Path | None,
    returns: Path | None,
    targets: Path | None,
) -> SourcePaths:
    """Resolve CLI options over configured paths and require all core datasets."""
    resolved = {
        "orders": orders or settings.sources.orders,
        "products": products or settings.sources.products,
        "inventory": inventory or settings.sources.inventory,
        "returns": returns or settings.sources.returns,
    }
    missing = [name for name, path in resolved.items() if path is None]
    if missing:
        raise DataSourceError(
            "Required source files are missing. Provide: " + ", ".join(missing) + "."
        )
    orders_path = resolved["orders"]
    products_path = resolved["products"]
    inventory_path = resolved["inventory"]
    returns_path = resolved["returns"]
    assert orders_path is not None
    assert products_path is not None
    assert inventory_path is not None
    assert returns_path is not None
    return SourcePaths(
        orders=Path(orders_path),
        products=Path(products_path),
        inventory=Path(inventory_path),
        returns=Path(returns_path),
        targets=targets or settings.sources.targets,
    )


def load_source_datasets(paths: SourcePaths) -> dict[DatasetType, LoadedDataset]:
    """Load configured paths through the common CSV/XLSX ingestion dispatcher."""
    path_mapping = {
        DatasetType.ORDERS: paths.orders,
        DatasetType.PRODUCTS: paths.products,
        DatasetType.INVENTORY: paths.inventory,
        DatasetType.RETURNS: paths.returns,
    }
    if paths.targets is not None:
        path_mapping[DatasetType.MONTHLY_TARGETS] = paths.targets
    for path in path_mapping.values():
        if not path.is_file():
            raise DataSourceError(f"The source file '{path}' does not exist or is not readable.")
    return {dataset_type: load_file(path) for dataset_type, path in path_mapping.items()}


def process_loaded_datasets(
    datasets: Mapping[DatasetType, LoadedDataset],
    settings: RetailFlowSettings,
    *,
    progress_callback: Callable[[ProcessingProgress], None] | None = None,
) -> ProcessingResult:
    """Run the canonical mapping, cleaning, validation, and merge pipeline."""
    pipeline = DataProcessingPipeline(
        default_currency=settings.report.default_currency,
        duplicate_strategy=settings.validation.duplicate_strategy,
    )
    return pipeline.process(
        datasets[DatasetType.ORDERS],
        datasets[DatasetType.PRODUCTS],
        datasets[DatasetType.INVENTORY],
        datasets[DatasetType.RETURNS],
        datasets.get(DatasetType.MONTHLY_TARGETS),
        progress_callback=progress_callback,
    )


def combined_validation(result: ProcessingResult) -> CombinedValidationResult:
    """Represent pipeline issues through the shared combined validation model."""
    return CombinedValidationResult(
        tuple(
            DatasetValidationResult(
                dataset_type=dataset_type,
                source_filename=(
                    result.source_metadata[dataset_type].filename
                    if dataset_type in result.source_metadata
                    else None
                ),
                total_rows=statistics.input_rows,
                issues=tuple(
                    issue
                    for issue in result.validation_issues
                    if issue.source_dataset is dataset_type
                ),
            )
            for dataset_type, statistics in result.statistics.by_dataset.items()
        )
    )


def validation_summary(result: ProcessingResult) -> ValidationSummary:
    """Calculate terminal-safe counts and the canonical rule-based quality score."""
    validation = combined_validation(result)
    return ValidationSummary(
        source_rows=result.statistics.total_input_rows,
        processed_rows=result.statistics.total_processed_rows,
        excluded_rows=result.statistics.total_excluded_rows,
        warnings=validation.warning_count,
        errors=validation.error_count,
        quality_score=validation.quality_score,
    )


def ensure_generation_allowed(
    result: ProcessingResult,
    settings: RetailFlowSettings,
    *,
    strict: bool,
) -> bool:
    """Reject blocking errors and enforce strict warning behavior.

    Returns True only when strict mode has warnings but configuration explicitly
    allows a workbook to be produced before returning a validation-failure exit.
    """
    blocking = [
        issue
        for issue in result.validation_issues
        if issue.severity is ValidationSeverity.ERROR and not issue.row_can_continue
    ]
    if blocking:
        raise CliValidationError(
            f"Validation found {len(blocking)} blocking error(s); no report was generated."
        )
    warnings = [
        issue
        for issue in result.validation_issues
        if issue.severity is ValidationSeverity.WARNING
    ]
    if strict and warnings:
        if settings.validation.allow_report_with_warnings_in_strict_mode:
            return True
        raise CliValidationError(
            f"Strict mode found {len(warnings)} warning(s); no report was generated."
        )
    return False


def parse_reporting_period(value: str | None, result: ProcessingResult) -> ReportingPeriod:
    """Parse YYYY-MM or YYYY-MM-DD:YYYY-MM-DD, otherwise derive source bounds."""
    if value:
        try:
            if len(value) == 7:
                start = pd.Period(value, freq="M").start_time.date()
                end = pd.Period(value, freq="M").end_time.date()
                return ReportingPeriod(start, end)
            start_text, end_text = value.split(":", 1)
            start = date.fromisoformat(start_text)
            end = date.fromisoformat(end_text)
        except (ValueError, TypeError) as error:
            raise ConfigurationError(
                "Reporting period must use YYYY-MM or YYYY-MM-DD:YYYY-MM-DD.",
                technical_detail=str(error),
            ) from error
        if start > end:
            raise ConfigurationError("Reporting-period start must not be after its end.")
        return ReportingPeriod(start, end)
    dates = pd.to_datetime(
        result.processed_orders.get("order_date", pd.Series(dtype="datetime64[ns]")),
        errors="coerce",
    ).dropna()
    if dates.empty:
        raise CliValidationError("A reporting period could not be derived from the order data.")
    return ReportingPeriod(dates.min().date(), dates.max().date())


def calculate_analytics(
    result: ProcessingResult,
    period: ReportingPeriod,
    settings: RetailFlowSettings,
) -> AnalyticsBundle:
    """Calculate report analytics through the existing analytics modules."""
    filters = AnalyticsFilters(date_from=period.start, date_to=period.end)
    sales = calculate_sales_analytics(result.processed_orders, result.returns, filters)
    returns = calculate_returns_analytics(result.processed_orders, result.returns, filters)
    inventory = calculate_inventory_metrics(
        result.inventory,
        result.processed_orders,
        result.returns,
        thresholds=settings.inventory,
        period_start=period.start,
        period_end=period.end,
    )
    recommendations = generate_recommendations(inventory, thresholds=settings.inventory)
    return AnalyticsBundle(sales, returns, inventory, recommendations)


def resolve_report_destination(
    output: Path | None,
    settings: RetailFlowSettings,
    generated_at: datetime,
) -> tuple[Path, str]:
    """Resolve --output as either an XLSX filename or an output directory."""
    if output is not None and output.suffix.casefold() == ".xlsx":
        return output.parent, output.name
    output_directory = output or settings.output.output_directory
    try:
        filename = settings.output.filename_pattern.format(
            timestamp=generated_at.strftime("%Y%m%d_%H%M%S")
        )
    except (KeyError, ValueError) as error:
        raise ConfigurationError(
            "The configured report filename pattern is invalid.",
            technical_detail=str(error),
        ) from error
    if not filename.casefold().endswith(".xlsx"):
        filename = f"{filename}.xlsx"
    return Path(output_directory), Path(filename).name


def create_run_repository(settings: RetailFlowSettings) -> RunRepository:
    """Create the same SQLAlchemy run repository used by the Streamlit service."""
    return open_run_repository(
        settings.storage.database_url,
        create_tables=settings.storage.create_tables,
    )


def _source_metadata(result: ProcessingResult) -> tuple[dict[str, str], dict[str, int]]:
    filenames = {
        dataset_type.value: metadata.filename
        for dataset_type, metadata in result.source_metadata.items()
    }
    counts = {
        dataset_type.value: statistics.input_rows
        for dataset_type, statistics in result.statistics.by_dataset.items()
    }
    return filenames, counts


def generate_report(
    result: ProcessingResult,
    analytics: AnalyticsBundle,
    period: ReportingPeriod,
    settings: RetailFlowSettings,
    *,
    output: Path | None,
    currency: str | None,
    overwrite: bool,
    strict: bool,
    stage_callback: StageCallback | None = None,
    repository: RunRepository | None = None,
) -> CliGenerationResult:
    """Generate a report and persist the same Pending/Running/final run lifecycle."""
    started_at = datetime.now(UTC)
    started = monotonic()
    currency_code = (currency or settings.report.default_currency).upper()
    output_directory, filename = resolve_report_destination(output, settings, started_at)
    summary = validation_summary(result)
    filenames, counts = _source_metadata(result)
    run_repository = repository or create_run_repository(settings)
    run = run_repository.create_run(
        reporting_period_start=period.start,
        reporting_period_end=period.end,
        source_filenames=filenames,
        source_row_counts=counts,
        configuration_snapshot={
            "settings": settings,
            "command": {
                "period": period.label,
                "currency": currency_code,
                "strict": strict,
                "overwrite": overwrite,
            },
        },
        application_version=__version__,
        started_at=started_at,
    )
    run_repository.mark_running(run.run_id)
    try:
        if stage_callback is not None:
            stage_callback("Generating Excel workbook")
        generator = ExcelReportGenerator(
            output_directory,
            company_name=settings.report.company_name,
            default_currency=currency_code,
            overwrite=overwrite,
        )
        report = generator.generate(
            result,
            analytics.sales,
            analytics.returns,
            inventory_analytics=analytics.inventory,
            recommendations=analytics.recommendations,
            filename=filename,
            report_id=run.run_id,
            generated_at=started_at,
            reporting_period=period.label,
            include_processed_data=settings.report.include_raw_data,
            include_data_quality_report=settings.report.include_quality_report,
            include_inventory_analysis=settings.report.include_inventory_analysis,
            include_returns_analysis=settings.report.include_returns_analysis,
            include_recommendations=settings.report.include_recommendations,
        )
        duration = round(monotonic() - started, 3)
        run_repository.mark_completed(
            run.run_id,
            completed_at=datetime.now(UTC),
            processed_row_count=summary.processed_rows,
            excluded_row_count=summary.excluded_rows,
            warning_count=summary.warnings,
            error_count=summary.errors,
            report_path=report.report_path,
            report_filename=report.report_path.name,
            report_size=report.file_size,
            duration_seconds=duration,
        )
        return CliGenerationResult(report, run.run_id, summary)
    except Exception as error:
        _mark_run_failed(run_repository, run, result, started, error)
        raise


def _mark_run_failed(
    repository: RunRepository,
    run: RunRecord,
    result: ProcessingResult,
    started: float,
    error: Exception,
) -> None:
    """Persist a safe CLI failure without masking the original exception."""
    summary = validation_summary(result)
    message = error.message if isinstance(error, RetailFlowError) else "Unexpected report failure."
    try:
        repository.mark_failed(
            run.run_id,
            failure_summary=message,
            completed_at=datetime.now(UTC),
            duration_seconds=round(monotonic() - started, 3),
            processed_row_count=summary.processed_rows,
            excluded_row_count=summary.excluded_rows,
            warning_count=summary.warnings,
            error_count=summary.errors,
        )
    except RetailFlowError:
        # The caller logs the original exception; persistence failure must not replace it.
        logger.exception("Could not persist failure state for CLI run %s", run.run_id)


def write_validation_report(
    result: ProcessingResult,
    destination: Path,
    settings: RetailFlowSettings,
) -> Path:
    """Write a focused validation workbook without generating management worksheets."""
    if destination.exists():
        raise ReportGenerationError(
            "The validation report already exists. Choose another output path."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.tmp.xlsx")
    summary = validation_summary(result)
    summary_frame = pd.DataFrame(
        {
            "metric": (
                "source_rows",
                "processed_rows",
                "excluded_rows",
                "warnings",
                "errors",
                "quality_score",
            ),
            "value": (
                summary.source_rows,
                summary.processed_rows,
                summary.excluded_rows,
                summary.warnings,
                summary.errors,
                summary.quality_score,
            ),
        }
    )
    try:
        with pd.ExcelWriter(temporary, engine="xlsxwriter") as writer:
            summary_frame.to_excel(writer, sheet_name="Summary", index=False)
            issues_to_dataframe(result.validation_issues).to_excel(
                writer, sheet_name="Issues", index=False
            )
            result.excluded_rows.to_excel(writer, sheet_name="Excluded Rows", index=False)
            safe_configuration = sanitize_configuration(settings)
            pd.DataFrame(
                [(key, str(value)) for key, value in safe_configuration.items()],
                columns=("key", "value"),
            ).to_excel(writer, sheet_name="Configuration", index=False)
        temporary.replace(destination)
    except Exception as error:
        temporary.unlink(missing_ok=True)
        raise ReportGenerationError(
            "The validation report could not be written.", technical_detail=str(error)
        ) from error
    return destination.resolve()


def exception_exit_code(error: BaseException) -> ExitCode:
    """Map known failures to the documented stable process exit code."""
    if isinstance(error, ConfigurationError):
        return ExitCode.CONFIGURATION_ERROR
    if isinstance(error, DataSourceError):
        return ExitCode.SOURCE_FILE_ERROR
    if isinstance(error, DataValidationError):
        return ExitCode.VALIDATION_FAILURE
    if isinstance(error, ReportGenerationError):
        return ExitCode.REPORT_GENERATION_FAILURE
    if isinstance(error, RetailFlowError):
        return ExitCode.REPORT_GENERATION_FAILURE
    return ExitCode.INTERNAL_ERROR


__all__ = [
    "AnalyticsBundle",
    "CliGenerationResult",
    "CliValidationError",
    "ExitCode",
    "ReportingPeriod",
    "SourcePaths",
    "ValidationSummary",
    "calculate_analytics",
    "combined_validation",
    "create_run_repository",
    "ensure_generation_allowed",
    "exception_exit_code",
    "generate_report",
    "load_source_datasets",
    "parse_reporting_period",
    "process_loaded_datasets",
    "resolve_report_destination",
    "resolve_source_paths",
    "validation_summary",
    "write_validation_report",
]
