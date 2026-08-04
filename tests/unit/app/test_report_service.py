"""Tests for safe Streamlit report-generation orchestration."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import openpyxl
import pytest
from app.services.dashboard_service import DashboardFilters, calculate_dashboard
from app.services.processing_service import issue_identifier, run_processing
from app.services.report_service import (
    LogoUpload,
    ReportRequest,
    ReportServiceError,
    check_report_prerequisites,
    default_report_request,
    generate_management_report,
    read_generated_report,
    validate_report_request,
)
from app.state import ApplicationStatus, StateKey

from retailflow.common.config import RetailFlowSettings
from retailflow.common.exceptions import ReportGenerationError
from retailflow.models import ProcessingResult
from retailflow.reporting.excel_report import ExcelReportGenerator
from retailflow.storage import Database, RunRepository
from retailflow.validation import DatasetType, ValidationIssue, ValidationSeverity

from .test_processing_service import _state


@pytest.fixture(autouse=True)
def _isolated_run_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RunRepository:
    database = Database(f"sqlite:///{tmp_path / 'report-history.sqlite3'}")
    database.create_tables()
    repository = RunRepository(database)
    monkeypatch.setattr(
        "app.services.report_service.get_run_repository",
        lambda: repository,
    )
    return repository


def _ready_state() -> dict[str, object]:
    state = _state()
    loaded = state[StateKey.LOADED_DATASETS.value]
    assert isinstance(loaded, dict)
    inventory = loaded["inventory"]
    inventory.dataframe["reserved_quantity"] = [0]
    inventory.dataframe["reorder_level"] = [5]
    inventory.dataframe["last_restock_date"] = ["2024-12-01"]
    products = loaded["products"]
    products.dataframe["category"] = ["Office"]
    processing = run_processing(state)
    dashboard = calculate_dashboard(
        processing.processed_orders,
        processing.inventory,
        processing.returns,
        DashboardFilters(),
        default_currency="EUR",
    )
    state[StateKey.SALES_ANALYTICS.value] = dashboard.sales_analytics
    state[StateKey.RETURNS_ANALYTICS.value] = dashboard.returns_analytics
    state[StateKey.INVENTORY_ANALYTICS.value] = dashboard.inventory_metrics
    state[StateKey.RECOMMENDATIONS.value] = dashboard.recommendations
    return state


def _request(output_directory: Path, **changes: object) -> ReportRequest:
    request = ReportRequest(
        report_name="management_report",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        currency="EUR",
        include_processed_data=True,
        include_data_quality_report=True,
        include_inventory_analysis=True,
        include_returns_analysis=True,
        include_recommendations=True,
        company_name="RetailFlow Test",
        report_title="January Management Report",
        prepared_by="Finance Team",
        output_directory=output_directory,
        overwrite=False,
    )
    return replace(request, **changes)


def test_defaults_use_typed_settings_and_processed_period() -> None:
    state = _ready_state()
    processing = state[StateKey.PROCESSING_RESULT.value]
    assert isinstance(processing, ProcessingResult)

    request = default_report_request(RetailFlowSettings(), processing)

    assert request.period_start == date(2025, 1, 1)
    assert request.period_end == date(2025, 1, 1)
    assert request.company_name == "RetailFlow Analytics"
    assert request.include_data_quality_report


def test_prerequisites_identify_missing_workflow_step() -> None:
    state = _state()
    prerequisite = check_report_prerequisites(state)
    assert not prerequisite.ready
    assert prerequisite.required_page == "Upload Data"

    processing = run_processing(state)
    prerequisite = check_report_prerequisites(state)
    assert not prerequisite.ready
    assert prerequisite.required_page == "Dashboard"
    assert processing is state[StateKey.PROCESSING_RESULT.value]


def test_unreviewed_warning_requires_data_quality_confirmation() -> None:
    state = _ready_state()
    processing = state[StateKey.PROCESSING_RESULT.value]
    assert isinstance(processing, ProcessingResult)
    warning = ValidationIssue(
        ValidationSeverity.WARNING,
        DatasetType.ORDERS,
        "orders.csv",
        2,
        "currency",
        "normalized_currency",
        "Currency was normalized.",
        "eur",
        "Confirm the normalized value.",
        True,
    )
    state[StateKey.PROCESSING_RESULT.value] = replace(
        processing, validation_issues=(warning,)
    )

    prerequisite = check_report_prerequisites(state)

    assert not prerequisite.ready
    assert prerequisite.required_page == "Data Quality"
    state[StateKey.WARNINGS_CONFIRMED.value] = True
    assert check_report_prerequisites(state).ready


def test_unreviewed_exclusion_requires_an_issue_action() -> None:
    state = _ready_state()
    processing = state[StateKey.PROCESSING_RESULT.value]
    assert isinstance(processing, ProcessingResult)
    issue = ValidationIssue(
        ValidationSeverity.ERROR,
        DatasetType.ORDERS,
        "orders.csv",
        2,
        "quantity",
        "quantity_not_positive",
        "Quantity must be positive.",
        -1,
        "Exclude the row.",
        False,
    )
    state[StateKey.PROCESSING_RESULT.value] = replace(
        processing, validation_issues=(issue,)
    )
    assert not check_report_prerequisites(state).ready

    state[StateKey.ISSUE_ACTIONS.value] = {
        issue_identifier(issue, 0): "Excluded from processing"
    }
    assert check_report_prerequisites(state).ready


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"report_name": "../report"}, "unsupported characters"),
        (
            {"period_start": date(2025, 2, 1), "period_end": date(2025, 1, 1)},
            "start date",
        ),
        ({"currency": "EURO"}, "three-letter code"),
        ({"company_name": " "}, "Company Name"),
    ],
)
def test_report_request_validation_is_user_friendly(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ReportServiceError, match=message):
        validate_report_request(_request(tmp_path, **changes))


def test_invalid_logo_content_is_rejected(tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        logo=LogoUpload("company.png", b"this is not a png"),
    )

    with pytest.raises(ReportServiceError, match="not a valid PNG"):
        validate_report_request(request)


def test_service_generates_selected_sections_and_stores_result(tmp_path: Path) -> None:
    state = _ready_state()
    progress = []
    request = _request(
        tmp_path,
        include_processed_data=False,
        include_data_quality_report=False,
        include_inventory_analysis=False,
        include_returns_analysis=False,
        include_recommendations=False,
    )

    result = generate_management_report(state, request, progress_callback=progress.append)

    assert result.report_path.exists()
    assert read_generated_report(result).startswith(b"PK")
    assert [event.step for event in progress] == list(range(1, 8))
    assert [event.label for event in progress] == [
        "Validating report configuration",
        "Preparing analytics",
        "Creating worksheets",
        "Creating charts",
        "Formatting workbook",
        "Saving report",
        "Verifying output",
    ]
    workbook = openpyxl.load_workbook(result.report_path, read_only=True)
    assert workbook.sheetnames == [
        "00_Cover",
        "01_Executive_Summary",
        "02_Sales_Analysis",
        "03_Product_Performance",
        "08_Report_Metadata",
    ]
    assert workbook["00_Cover"]["A1"].value == "January Management Report"
    assert state[StateKey.GENERATED_REPORT.value] is result
    assert state[StateKey.APPLICATION_STATUS.value] is ApplicationStatus.REPORT_GENERATED
    assert result.quality_report.startswith(b"PK")


def test_existing_report_requires_explicit_overwrite(tmp_path: Path) -> None:
    state = _ready_state()
    request = _request(tmp_path)
    generate_management_report(state, request)

    with pytest.raises(ReportGenerationError, match="already exists"):
        generate_management_report(state, request)

    assert state[StateKey.APPLICATION_STATUS.value] is ApplicationStatus.FAILED


def test_unexpected_generator_failure_is_wrapped_and_sets_failed_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_generation(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("worksheet exploded")

    state = _ready_state()
    monkeypatch.setattr(ExcelReportGenerator, "generate", fail_generation)

    with pytest.raises(ReportServiceError, match="could not be generated") as captured:
        generate_management_report(state, _request(tmp_path))

    assert "worksheet exploded" in (captured.value.technical_detail or "")
    assert state[StateKey.APPLICATION_STATUS.value] is ApplicationStatus.FAILED
