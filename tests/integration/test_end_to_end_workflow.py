"""Deterministic end-to-end coverage of the complete management-report workflow."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
from scripts.generate_demo_data import generate_demo_data

from retailflow import __version__
from retailflow.analytics import (
    calculate_inventory_metrics,
    calculate_returns_analytics,
    calculate_sales_analytics,
    generate_recommendations,
)
from retailflow.ingestion import load_file
from retailflow.models import ProcessingStage
from retailflow.pipeline import DataProcessingPipeline
from retailflow.reporting.excel_report import REQUIRED_WORKSHEETS, generate_excel_report
from retailflow.storage import Database, RunRepository, RunStatus
from retailflow.validation import DatasetType


def test_deterministic_sources_complete_reporting_and_history_workflow(
    tmp_path: Path,
) -> None:
    """Exercise real adapters and verify stable KPIs, workbook, and persisted run."""
    source_directory = tmp_path / "sources"
    generation = generate_demo_data(
        source_directory,
        number_of_orders=40,
        number_of_products=8,
        random_seed=2026,
        include_invalid_rows=False,
    )
    loaded = {
        DatasetType.ORDERS: load_file(source_directory / "orders.csv"),
        DatasetType.PRODUCTS: load_file(source_directory / "products.xlsx"),
        DatasetType.INVENTORY: load_file(source_directory / "inventory.csv"),
        DatasetType.RETURNS: load_file(source_directory / "returns.xlsx"),
        DatasetType.MONTHLY_TARGETS: load_file(
            source_directory / "monthly_targets.csv"
        ),
    }
    progress_stages: list[ProcessingStage] = []

    processing = DataProcessingPipeline().process(
        loaded[DatasetType.ORDERS],
        loaded[DatasetType.PRODUCTS],
        loaded[DatasetType.INVENTORY],
        loaded[DatasetType.RETURNS],
        loaded[DatasetType.MONTHLY_TARGETS],
        progress_callback=lambda progress: progress_stages.append(progress.stage),
    )

    assert progress_stages == list(ProcessingStage)
    assert processing.statistics.total_input_rows == (
        generation.orders
        + generation.products
        + generation.inventory_rows
        + generation.returns
        + generation.targets
    )
    assert processing.excluded_rows.empty
    assert processing.validation_issues == ()
    assert {"source_file", "source_row_number", "processing_status"} <= set(
        processing.processed_orders
    )
    assert processing.processed_orders["processing_status"].eq("processed").all()

    sales = calculate_sales_analytics(processing.processed_orders, processing.returns)
    returns = calculate_returns_analytics(processing.processed_orders, processing.returns)
    inventory = calculate_inventory_metrics(
        processing.inventory,
        processing.processed_orders,
        processing.returns,
        period_start="2025-01-01",
        period_end="2025-12-31",
        as_of_date="2025-12-31",
    )
    recommendations = generate_recommendations(inventory)

    # These values are fixed by the generator seed and independently exercise
    # ingestion, normalization, joins, refund allocation, and KPI aggregation.
    assert sales.kpis.gross_revenue == Decimal("23941.41")
    assert sales.kpis.discount_amount == Decimal("873.42")
    assert sales.kpis.refund_amount == Decimal("1917.68")
    assert sales.kpis.net_revenue == Decimal("21150.31")
    assert sales.kpis.cost_of_goods_sold == Decimal("12105.17")
    assert sales.kpis.gross_profit == Decimal("9045.14")
    assert sales.kpis.gross_margin_percent == Decimal("42.77")
    assert sales.kpis.orders == 31
    assert sales.kpis.average_order_value == Decimal("682.27")
    assert returns.kpis.return_rate_percent == Decimal("6.90")
    assert len(inventory) == generation.inventory_rows
    assert recommendations

    report_id = "E2E-2025-001"
    generated = generate_excel_report(
        processing,
        sales,
        returns,
        inventory_analytics=inventory,
        recommendations=recommendations,
        output_directory=tmp_path / "reports",
        filename="retailflow-e2e.xlsx",
        company_name="RetailFlow Test Company",
        default_currency="EUR",
        report_id=report_id,
        generated_at=datetime(2026, 1, 1, 9, tzinfo=UTC),
        reporting_period="2025-01-01 to 2025-12-31",
    )

    workbook = openpyxl.load_workbook(generated.report_path, data_only=False)
    assert workbook.sheetnames == list(REQUIRED_WORKSHEETS)
    assert workbook["00_Cover"]["B5"].value == report_id
    assert workbook["01_Executive_Summary"]["A5"].value == 21150.31
    assert workbook["08_Report_Metadata"]["B3"].value == report_id

    database = Database(f"sqlite:///{tmp_path / 'run-history.sqlite3'}")
    database.create_tables()
    repository = RunRepository(database)
    started_at = datetime(2026, 1, 1, 8, 59, tzinfo=UTC)
    run = repository.create_run(
        reporting_period_start=date(2025, 1, 1),
        reporting_period_end=date(2025, 12, 31),
        source_filenames={
            dataset.value: metadata.filename
            for dataset, metadata in processing.source_metadata.items()
        },
        source_row_counts={
            dataset.value: statistics.input_rows
            for dataset, statistics in processing.statistics.by_dataset.items()
        },
        configuration_snapshot={
            "currency": "EUR",
            "api_token": "must-not-be-persisted",
        },
        application_version=__version__,
        started_at=started_at,
    )
    repository.mark_running(run.run_id)
    completed = repository.mark_completed(
        run.run_id,
        completed_at=datetime(2026, 1, 1, 9, tzinfo=UTC),
        processed_row_count=processing.statistics.total_processed_rows,
        excluded_row_count=processing.statistics.total_excluded_rows,
        warning_count=0,
        error_count=0,
        report_path=generated.report_path,
        report_filename=generated.report_path.name,
        report_size=generated.file_size,
        duration_seconds=60.0,
    )

    stored = repository.get_run(run.run_id)
    assert completed.status is RunStatus.COMPLETED
    assert stored is not None
    assert stored.status is RunStatus.COMPLETED
    assert stored.run_id == completed.run_id
    assert stored.report_path == str(generated.report_path)
    assert stored.processed_row_count == processing.statistics.total_processed_rows
    assert "must-not-be-persisted" not in str(stored.configuration_snapshot)
    database.dispose()
