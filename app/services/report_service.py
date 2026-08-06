"""Safe service-layer orchestration for management-report generation."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

import pandas as pd

from app.services.dashboard_service import DashboardFilters, calculate_dashboard
from app.services.processing_service import (
    generate_quality_report,
    has_blocking_structural_errors,
    issue_identifier,
)
from app.services.run_history_service import get_run_repository
from app.state import (
    ApplicationStatus,
    SessionState,
    StateKey,
    initialize_state,
)
from retailflow import __version__
from retailflow.analytics.models import ReturnsAnalyticsResult, SalesAnalyticsResult
from retailflow.analytics.recommendations import Recommendation
from retailflow.common.config import RetailFlowSettings
from retailflow.common.exceptions import RetailFlowError
from retailflow.models import ProcessingResult
from retailflow.reporting.excel_report import (
    ExcelReportGenerator,
    ReportGenerationResult,
    ReportGenerationStatistics,
)
from retailflow.storage import RunRecord, RunRepository
from retailflow.validation import ValidationSeverity

logger = logging.getLogger("retailflow.app.reporting")

_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_LOGO_LIMIT_BYTES = 5 * 1024 * 1024
_PROGRESS_LABELS = (
    "Validating report configuration",
    "Preparing analytics",
    "Creating worksheets",
    "Creating charts",
    "Formatting workbook",
    "Saving report",
    "Verifying output",
)


class ReportServiceError(RetailFlowError):
    """Raised when a report request cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class LogoUpload:
    """A validated-in-service representation of an uploaded company logo."""

    filename: str
    content: bytes


@dataclass(frozen=True, slots=True)
class ReportRequest:
    """User-controlled report settings passed from the form to the service."""

    report_name: str
    period_start: date
    period_end: date
    currency: str
    include_processed_data: bool
    include_data_quality_report: bool
    include_inventory_analysis: bool
    include_returns_analysis: bool
    include_recommendations: bool
    company_name: str
    report_title: str
    prepared_by: str
    output_directory: Path = Path("output")
    logo: LogoUpload | None = None
    overwrite: bool = False

    @property
    def filename(self) -> str:
        """Return the normalized XLSX filename."""
        name = self.report_name.strip()
        return name if name.casefold().endswith(".xlsx") else f"{name}.xlsx"

    @property
    def reporting_period(self) -> str:
        """Return the selected inclusive reporting-period label."""
        return f"{self.period_start:%Y-%m-%d} to {self.period_end:%Y-%m-%d}"


@dataclass(frozen=True, slots=True)
class ReportProgressEvent:
    """One user-facing report generation stage."""

    step: int
    total_steps: int
    label: str

    @property
    def fraction(self) -> float:
        """Return progress as a value between zero and one."""
        return self.step / self.total_steps


@dataclass(frozen=True, slots=True)
class ReportPrerequisites:
    """Prerequisite status and the page that can resolve it."""

    ready: bool
    message: str = ""
    required_page: str | None = None


@dataclass(frozen=True, slots=True)
class ReportServiceResult:
    """Download-ready report result plus UI summary information."""

    generation: ReportGenerationResult
    report_id: str
    generated_at: datetime
    generation_seconds: float
    warning_count: int
    quality_report: bytes

    @property
    def report_path(self) -> Path:
        """Return the verified workbook path."""
        return self.generation.report_path

    @property
    def file_size(self) -> int:
        """Return workbook size in bytes."""
        return self.generation.file_size

    @property
    def statistics(self) -> ReportGenerationStatistics:
        """Expose generation statistics for existing application consumers."""
        return self.generation.statistics


type ReportProgressCallback = Callable[[ReportProgressEvent], None]


def _state_value(state: SessionState, key: StateKey) -> object:
    return state[key.value]


def check_report_prerequisites(state: SessionState) -> ReportPrerequisites:
    """Check processing, analytics, and explicit data-quality review decisions."""
    initialize_state(state)
    processing = _state_value(state, StateKey.PROCESSING_RESULT)
    if not isinstance(processing, ProcessingResult):
        return ReportPrerequisites(
            False,
            "No validated dataset is available. Upload and validate your source files first.",
            "Upload Data",
        )
    if has_blocking_structural_errors(processing):
        return ReportPrerequisites(
            False,
            "Blocking structural errors must be resolved before a report can be generated.",
            "Data Quality",
        )

    actions = _state_value(state, StateKey.ISSUE_ACTIONS)
    action_mapping = actions if isinstance(actions, Mapping) else {}
    unresolved = [
        issue
        for occurrence, issue in enumerate(processing.validation_issues)
        if not issue.row_can_continue
        and issue_identifier(issue, occurrence) not in action_mapping
    ]
    warnings = [
        issue
        for issue in processing.validation_issues
        if issue.severity is ValidationSeverity.WARNING
    ]
    if unresolved or (warnings and not bool(_state_value(state, StateKey.WARNINGS_CONFIRMED))):
        return ReportPrerequisites(
            False,
            "Review all exclusions and explicitly confirm warnings before generating a report.",
            "Data Quality",
        )

    sales_ready = isinstance(
        _state_value(state, StateKey.SALES_ANALYTICS), SalesAnalyticsResult
    )
    returns_ready = isinstance(
        _state_value(state, StateKey.RETURNS_ANALYTICS), ReturnsAnalyticsResult
    )
    if not sales_ready or not returns_ready:
        return ReportPrerequisites(
            False,
            "Calculated analytics are required. Open Dashboard to prepare them first.",
            "Dashboard",
        )
    if not isinstance(_state_value(state, StateKey.INVENTORY_ANALYTICS), pd.DataFrame):
        return ReportPrerequisites(
            False,
            "Inventory analytics are required. Open Dashboard to prepare them first.",
            "Dashboard",
        )
    return ReportPrerequisites(True)


def default_report_request(
    settings: RetailFlowSettings,
    processing: ProcessingResult,
    *,
    today: date | None = None,
) -> ReportRequest:
    """Build form defaults from typed application settings and processed dates."""
    dates = pd.to_datetime(
        processing.processed_orders.get("order_date", pd.Series(dtype="datetime64[ns]")),
        errors="coerce",
    ).dropna()
    fallback = today or date.today()
    start = dates.min().date() if not dates.empty else fallback
    end = dates.max().date() if not dates.empty else fallback
    return ReportRequest(
        report_name=f"retailflow_report_{end:%Y%m%d}",
        period_start=start,
        period_end=end,
        currency=settings.report.default_currency,
        include_processed_data=settings.report.include_raw_data,
        include_data_quality_report=settings.report.include_quality_report,
        include_inventory_analysis=settings.report.include_inventory_analysis,
        include_returns_analysis=settings.report.include_returns_analysis,
        include_recommendations=settings.report.include_recommendations,
        company_name=settings.report.company_name,
        report_title="RetailFlow Analytics Management Report",
        prepared_by=settings.report.company_name,
        output_directory=settings.output.output_directory,
    )


def validate_report_request(request: ReportRequest) -> None:
    """Validate report configuration without exposing technical filesystem details."""
    required = {
        "Report Name": request.report_name,
        "Company Name": request.company_name,
        "Report Title": request.report_title,
        "Prepared By": request.prepared_by,
    }
    empty_fields = [label for label, value in required.items() if not value.strip()]
    if empty_fields:
        raise ReportServiceError(f"Enter a value for {', '.join(empty_fields)}.")
    raw_name = request.report_name.strip()
    if raw_name in {".", ".."} or _INVALID_FILENAME.search(raw_name):
        raise ReportServiceError(
            "The report filename contains unsupported characters. Use letters, numbers, "
            "spaces, hyphens, or underscores."
        )
    if request.period_start > request.period_end:
        raise ReportServiceError("The reporting-period start date must not be after the end date.")
    currency = request.currency.strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ReportServiceError("Currency must be a three-letter code such as EUR or USD.")
    if request.output_directory.exists() and not request.output_directory.is_dir():
        raise ReportServiceError("The configured report output path is not a directory.")
    existing_parent = request.output_directory
    while not existing_parent.exists() and existing_parent != existing_parent.parent:
        existing_parent = existing_parent.parent
    if not existing_parent.is_dir() or not os.access(existing_parent, os.W_OK):
        raise ReportServiceError("The configured report output directory is not writable.")
    if request.logo is not None:
        _validate_logo(request.logo)


def _validate_logo(logo: LogoUpload) -> None:
    suffix = Path(logo.filename).suffix.casefold()
    if suffix not in {".png", ".jpg", ".jpeg"}:
        raise ReportServiceError("Company logo must be a PNG or JPEG image.")
    if not logo.content or len(logo.content) > _LOGO_LIMIT_BYTES:
        raise ReportServiceError("Company logo must be a non-empty image no larger than 5 MB.")
    is_png = logo.content.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = logo.content.startswith(b"\xff\xd8\xff")
    if (suffix == ".png" and not is_png) or (suffix in {".jpg", ".jpeg"} and not is_jpeg):
        raise ReportServiceError("The uploaded company logo is not a valid PNG or JPEG file.")


def validate_logo_upload(logo: LogoUpload) -> None:
    """Validate an uploaded logo using the same rules as report generation."""
    _validate_logo(logo)


def _emit(callback: ReportProgressCallback | None, step: int) -> None:
    if callback is not None:
        callback(ReportProgressEvent(step, len(_PROGRESS_LABELS), _PROGRESS_LABELS[step - 1]))


def _recommendations(value: object) -> Iterable[Recommendation]:
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
        return tuple(item for item in value if isinstance(item, Recommendation))
    return ()


def generate_management_report(
    state: SessionState,
    request: ReportRequest,
    *,
    progress_callback: ReportProgressCallback | None = None,
    generator_factory: type[ExcelReportGenerator] = ExcelReportGenerator,
    run_repository: RunRepository | None = None,
) -> ReportServiceResult:
    """Validate session inputs, generate and verify a downloadable Excel report."""
    initialize_state(state)
    started = monotonic()
    started_at = datetime.now(UTC)
    current_stage = _PROGRESS_LABELS[0]
    repository: RunRepository | None = None
    run: RunRecord | None = None
    processing: ProcessingResult | None = None
    state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.PROCESSING
    try:
        _emit(progress_callback, 1)
        prerequisite = check_report_prerequisites(state)
        if not prerequisite.ready:
            raise ReportServiceError(prerequisite.message)
        validate_report_request(request)

        current_stage = _PROGRESS_LABELS[1]
        _emit(progress_callback, 2)
        processing_value = _state_value(state, StateKey.PROCESSING_RESULT)
        sales = _state_value(state, StateKey.SALES_ANALYTICS)
        returns = _state_value(state, StateKey.RETURNS_ANALYTICS)
        inventory = _state_value(state, StateKey.INVENTORY_ANALYTICS)
        assert isinstance(processing_value, ProcessingResult)
        processing = processing_value
        assert isinstance(sales, SalesAnalyticsResult)
        assert isinstance(returns, ReturnsAnalyticsResult)
        assert isinstance(inventory, pd.DataFrame)
        period_analytics = calculate_dashboard(
            processing.processed_orders,
            processing.inventory,
            processing.returns,
            DashboardFilters(
                date_from=request.period_start,
                date_to=request.period_end,
            ),
            default_currency=request.currency.strip().upper(),
        )
        actions = _state_value(state, StateKey.ISSUE_ACTIONS)
        import_settings = _state_value(state, StateKey.IMPORT_SETTINGS)
        repository = run_repository or get_run_repository()
        run = repository.create_run(
            reporting_period_start=request.period_start,
            reporting_period_end=request.period_end,
            source_filenames={
                dataset_type.value: metadata.filename
                for dataset_type, metadata in processing.source_metadata.items()
            },
            source_row_counts={
                dataset_type.value: statistics.input_rows
                for dataset_type, statistics in processing.statistics.by_dataset.items()
            },
            configuration_snapshot={
                "report": request,
                "import": import_settings if isinstance(import_settings, Mapping) else {},
            },
            application_version=__version__,
            started_at=started_at,
        )
        repository.mark_running(run.run_id)
        quality_bytes = generate_quality_report(
            processing,
            actions=actions if isinstance(actions, Mapping) else None,
            import_settings=import_settings if isinstance(import_settings, Mapping) else None,
        )
        report_id = run.run_id
        generated_at = datetime.now(UTC)

        with TemporaryDirectory(prefix="retailflow-report-") as temp_directory:
            logo_path: Path | None = None
            if request.logo is not None:
                logo_suffix = Path(request.logo.filename).suffix.lower()
                logo_path = Path(temp_directory) / f"logo{logo_suffix}"
                logo_path.write_bytes(request.logo.content)
            for step in range(3, 7):
                current_stage = _PROGRESS_LABELS[step - 1]
                _emit(progress_callback, step)
            generator = generator_factory(
                request.output_directory,
                company_name=request.company_name.strip(),
                default_currency=request.currency.strip().upper(),
                overwrite=request.overwrite,
            )
            generation = generator.generate(
                processing,
                period_analytics.sales_analytics,
                period_analytics.returns_analytics,
                inventory_analytics=period_analytics.inventory_metrics,
                recommendations=_recommendations(period_analytics.recommendations),
                filename=request.filename,
                report_id=report_id,
                generated_at=generated_at,
                reporting_period=request.reporting_period,
                prepared_by=request.prepared_by.strip(),
                report_title=request.report_title.strip(),
                logo_path=logo_path,
                include_processed_data=request.include_processed_data,
                include_data_quality_report=request.include_data_quality_report,
                include_inventory_analysis=request.include_inventory_analysis,
                include_returns_analysis=request.include_returns_analysis,
                include_recommendations=request.include_recommendations,
            )

        current_stage = _PROGRESS_LABELS[6]
        _emit(progress_callback, 7)
        if not generation.report_path.is_file() or generation.file_size <= 0:
            generation.report_path.unlink(missing_ok=True)
            raise ReportServiceError(
                "The generated report could not be verified. Please try again."
            )
        result = ReportServiceResult(
            generation=generation,
            report_id=report_id,
            generated_at=generated_at,
            generation_seconds=round(monotonic() - started, 3),
            warning_count=sum(
                issue.severity is ValidationSeverity.WARNING
                for issue in processing.validation_issues
            ),
            quality_report=quality_bytes,
        )
        repository.mark_completed(
            run.run_id,
            completed_at=datetime.now(UTC),
            processed_row_count=processing.statistics.total_processed_rows,
            excluded_row_count=processing.statistics.total_excluded_rows,
            warning_count=result.warning_count,
            error_count=sum(
                issue.severity is ValidationSeverity.ERROR
                for issue in processing.validation_issues
            ),
            report_path=result.report_path,
            report_filename=result.report_path.name,
            report_size=result.file_size,
            duration_seconds=result.generation_seconds,
        )
        state[StateKey.GENERATED_REPORT.value] = result
        state[StateKey.LAST_SUCCESSFUL_RUN.value] = generated_at
        state[StateKey.SELECTED_REPORTING_PERIOD.value] = request.reporting_period
        stored_settings = _state_value(state, StateKey.REPORT_SETTINGS)
        settings_mapping = dict(stored_settings) if isinstance(stored_settings, Mapping) else {}
        settings_mapping["generation"] = request
        state[StateKey.REPORT_SETTINGS.value] = settings_mapping
        state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.REPORT_GENERATED
        logger.info(
            "Generated report %s with %d processed rows and %d warnings",
            report_id,
            result.statistics.processed_order_rows,
            result.warning_count,
        )
        return result
    except MemoryError as error:
        state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.FAILED
        logger.exception("Report generation ran out of memory during '%s'", current_stage)
        service_error = ReportServiceError(
            "There is not enough memory to create this report. Exclude processed data or "
            "reduce the reporting period and try again.",
            technical_detail=f"Stage: {current_stage}",
        )
        _save_failed_run(repository, run, processing, current_stage, started, service_error.message)
        raise service_error from error
    except RetailFlowError as error:
        state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.FAILED
        logger.exception("Report generation failed during '%s'", current_stage)
        _save_failed_run(repository, run, processing, current_stage, started, error.message)
        raise
    except Exception as error:
        state[StateKey.APPLICATION_STATUS.value] = ApplicationStatus.FAILED
        logger.exception("Unexpected report failure during '%s'", current_stage)
        service_error = ReportServiceError(
            "The Excel report could not be generated. Review the settings and try again.",
            technical_detail=f"Stage: {current_stage}; {error}",
        )
        _save_failed_run(repository, run, processing, current_stage, started, service_error.message)
        raise service_error from error


def _save_failed_run(
    repository: RunRepository | None,
    run: RunRecord | None,
    processing: ProcessingResult | None,
    stage: str,
    started: float,
    message: str,
) -> None:
    """Persist a safe failure summary without ever masking the original exception."""
    if repository is None or run is None:
        return
    issues = processing.validation_issues if processing is not None else ()
    try:
        repository.mark_failed(
            run.run_id,
            failure_summary=f"{message} Stage: {stage}.",
            completed_at=datetime.now(UTC),
            duration_seconds=round(monotonic() - started, 3),
            processed_row_count=(
                processing.statistics.total_processed_rows if processing is not None else 0
            ),
            excluded_row_count=(
                processing.statistics.total_excluded_rows if processing is not None else 0
            ),
            warning_count=sum(
                issue.severity is ValidationSeverity.WARNING for issue in issues
            ),
            error_count=sum(issue.severity is ValidationSeverity.ERROR for issue in issues),
        )
    except RetailFlowError:
        logger.exception("Could not persist failure status for run %s", run.run_id)


def read_generated_report(result: ReportServiceResult) -> bytes:
    """Read a verified generated workbook without exposing filesystem failures."""
    try:
        if not result.report_path.is_file():
            raise FileNotFoundError(result.report_path)
        content = result.report_path.read_bytes()
    except OSError as error:
        raise ReportServiceError(
            "The generated report is no longer available for download.",
            technical_detail=str(error),
        ) from error
    if not content:
        raise ReportServiceError("The generated report is empty and cannot be downloaded.")
    return content


__all__ = [
    "LogoUpload",
    "ReportPrerequisites",
    "ReportProgressEvent",
    "ReportRequest",
    "ReportServiceError",
    "ReportServiceResult",
    "check_report_prerequisites",
    "default_report_request",
    "generate_management_report",
    "read_generated_report",
    "validate_logo_upload",
    "validate_report_request",
]
