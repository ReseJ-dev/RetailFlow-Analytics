import pandas as pd
from app.components.issue_table import (
    IssueFilters,
    build_issue_views,
    filter_issue_views,
)
from app.components.quality_summary import quality_score_interpretation
from app.services.processing_service import combined_validation_result
from app.state import AppPage, StateKey
from streamlit.testing.v1 import AppTest

from retailflow.ingestion.models import FileMetadata
from retailflow.models import (
    DatasetProcessingStatistics,
    ProcessingResult,
    ProcessingStatistics,
)
from retailflow.validation import DatasetType, ValidationIssue, ValidationSeverity


def _issue(
    severity: ValidationSeverity,
    code: str,
    *,
    row_number: int | None,
    field: str | None,
    original_value: object,
    can_continue: bool,
) -> ValidationIssue:
    return ValidationIssue(
        severity=severity,
        source_dataset=DatasetType.ORDERS,
        source_filename="orders.csv",
        row_number=row_number,
        field=field,
        issue_code=code,
        message=f"Issue for {code}.",
        original_value=original_value,
        recommended_action=f"Resolve {code} before continuing.",
        row_can_continue=can_continue,
    )


def _processing_result() -> ProcessingResult:
    issues = (
        _issue(
            ValidationSeverity.ERROR,
            "missing_required_column",
            row_number=None,
            field="order_id",
            original_value="order_id",
            can_continue=False,
        ),
        _issue(
            ValidationSeverity.WARNING,
            "normalized_value",
            row_number=2,
            field="country",
            original_value="A" * 240,
            can_continue=True,
        ),
        _issue(
            ValidationSeverity.ERROR,
            "negative_quantity",
            row_number=3,
            field="quantity",
            original_value=-2,
            can_continue=False,
        ),
    )
    statistics = ProcessingStatistics(
        {
            DatasetType.ORDERS: DatasetProcessingStatistics(
                input_rows=3,
                processed_rows=1,
                excluded_rows=1,
                issue_count=len(issues),
            )
        }
    )
    metadata = FileMetadata(
        filename="orders.csv",
        file_type="csv",
        file_size=120,
        row_count=3,
        column_count=2,
        columns=("order_id", "quantity"),
    )
    return ProcessingResult(
        processed_orders=pd.DataFrame({"order_id": ["O-1"]}),
        products=pd.DataFrame(),
        inventory=pd.DataFrame(),
        returns=pd.DataFrame(),
        targets=pd.DataFrame(),
        excluded_rows=pd.DataFrame(
            {
                "source_file": ["orders.csv"],
                "source_row_number": [3],
                "processing_status": ["excluded"],
            }
        ),
        validation_issues=issues,
        statistics=statistics,
        source_metadata={DatasetType.ORDERS: metadata},
    )


def _open_quality_page(result: ProcessingResult) -> AppTest:
    app = AppTest.from_file("app/main.py", default_timeout=10).run()
    app.session_state[StateKey.PROCESSING_RESULT.value] = result
    app.session_state[StateKey.VALIDATION_RESULT.value] = combined_validation_result(result)
    app.session_state[StateKey.CURRENT_PAGE.value] = AppPage.DATA_QUALITY
    return app.run()


def test_score_interpretation_always_provides_text() -> None:
    assert quality_score_interpretation(98)[0] == "Excellent data health"
    assert quality_score_interpretation(90)[0] == "Good data health"
    assert quality_score_interpretation(75)[0] == "Review recommended"
    assert quality_score_interpretation(40)[0] == "Significant issues require attention"


def test_issue_filters_cover_every_requested_dimension() -> None:
    result = _processing_result()
    views = build_issue_views(result.validation_issues)

    filtered = filter_issue_views(
        views,
        IssueFilters(
            datasets=("orders",),
            severities=("warning",),
            categories=("Transformation Warnings",),
            fields=("country",),
            filenames=("orders.csv",),
            processing_statuses=("Reviewable warning",),
            search="normalized_value",
        ),
    )

    assert len(filtered) == 1
    assert filtered[0].issue.row_number == 2
    assert len(views) == 3


def test_data_quality_page_shows_health_traceability_and_blocking_state() -> None:
    app = _open_quality_page(_processing_result())

    assert not app.exception
    assert [metric.label for metric in app.metric[:6]] == [
        "Overall Quality Score",
        "Total Rows",
        "Clean Rows",
        "Warning Rows",
        "Excluded Rows",
        "Blocking Errors",
    ]
    assert app.metric[0].value == "0.0%"
    assert app.metric[5].value == "1"
    assert any(
        "Significant issues require attention" in markdown.value for markdown in app.markdown
    )
    assert [control.label for control in app.multiselect[:6]] == [
        "Dataset",
        "Severity",
        "Issue category",
        "Field",
        "Filename",
        "Processing status",
    ]
    assert any("Dashboard unavailable" in markdown.value for markdown in app.markdown)
    continue_button = next(
        button for button in app.button if button.label == "Continue to Dashboard"
    )
    assert continue_button.disabled
    table = app.dataframe[0].value
    assert list(table.columns) == [
        "Severity",
        "Dataset",
        "Source Filename",
        "Source Row",
        "Field",
        "Issue Code",
        "Issue",
        "Original Value",
        "Recommended Action",
        "Continuation Status",
    ]
    assert "orders.csv" in set(table["Source Filename"])
    assert any(code.value == "A" * 240 for code in app.code)
    assert any(button.label == "Download Error Report" for button in app.get("download_button"))


def test_presentation_filter_does_not_replace_processing_result() -> None:
    result = _processing_result()
    app = _open_quality_page(result)
    severity_filter = next(item for item in app.multiselect if item.label == "Severity")

    app = severity_filter.select("warning").run()

    assert not app.exception
    assert len(app.dataframe[0].value) == 1
    stored = app.session_state[StateKey.PROCESSING_RESULT.value]
    assert stored is result
    assert stored.validation_issues == result.validation_issues
