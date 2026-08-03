"""Integration tests for the end-to-end data-processing pipeline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from scripts.generate_demo_data import generate_demo_data

from retailflow.common.exceptions import DataValidationError
from retailflow.ingestion import load_file
from retailflow.ingestion.models import LoadedDataset
from retailflow.models import ProcessingProgress, ProcessingStage
from retailflow.pipeline import DataProcessingPipeline
from retailflow.transformation.merger import safe_many_to_one_merge
from retailflow.validation import DatasetType


def load_demo_files(directory: Path) -> dict[str, LoadedDataset]:
    return {
        "orders": load_file(directory / "orders.csv"),
        "products": load_file(directory / "products.xlsx"),
        "inventory": load_file(directory / "inventory.csv"),
        "returns": load_file(directory / "returns.xlsx"),
        "targets": load_file(directory / "monthly_targets.csv"),
    }


def test_pipeline_processes_generated_demo_files_with_traceability(
    tmp_path: Path,
) -> None:
    summary = generate_demo_data(
        tmp_path,
        number_of_orders=30,
        number_of_products=10,
        random_seed=7,
        include_invalid_rows=True,
    )
    loaded = load_demo_files(tmp_path)
    progress: list[ProcessingProgress] = []

    result = DataProcessingPipeline().process(
        loaded["orders"],
        loaded["products"],
        loaded["inventory"],
        loaded["returns"],
        loaded["targets"],
        progress_callback=progress.append,
    )

    assert 0 < len(result.processed_orders) < summary.orders
    assert not result.processed_orders.duplicated(["order_id", "product_id"]).any()
    assert (
        len(result.processed_orders)
        == result.statistics.by_dataset[DatasetType.ORDERS].processed_rows
    )
    assert {"product_name", "reporting_month", "target_revenue_target"} <= set(
        result.processed_orders
    )
    assert {"source_file", "source_row_number", "processing_status"} <= set(result.processed_orders)
    assert result.processed_orders["processing_status"].eq("processed").all()
    assert not result.excluded_rows.empty
    assert result.excluded_rows["processing_status"].eq("excluded").all()
    assert result.excluded_rows["exclusion_reason"].notna().all()
    assert DatasetType.ORDERS in result.source_metadata
    assert result.statistics.total_input_rows == (
        summary.orders
        + summary.products
        + summary.inventory_rows
        + summary.returns
        + summary.targets
    )
    assert result.statistics.total_excluded_rows == len(result.excluded_rows)
    assert [update.stage for update in progress] == list(ProcessingStage)
    assert progress[-1].fraction == 1.0


def test_pipeline_reports_unknown_products_and_invalid_returns_without_crashing(
    tmp_path: Path,
) -> None:
    generate_demo_data(
        tmp_path,
        number_of_orders=20,
        number_of_products=8,
        random_seed=11,
        include_invalid_rows=True,
    )
    loaded = load_demo_files(tmp_path)

    result = DataProcessingPipeline().process(
        loaded["orders"],
        loaded["products"],
        loaded["inventory"],
        loaded["returns"],
        loaded["targets"],
    )

    issue_codes = {issue.issue_code for issue in result.validation_issues}
    assert "unknown_product_id" in issue_codes
    assert "unknown_order_id" in issue_codes
    assert "P_UNKNOWN" not in set(result.processed_orders["product_id"])
    assert "O_MISSING" not in set(result.returns["order_id"])


def test_targets_are_optional(tmp_path: Path) -> None:
    generate_demo_data(
        tmp_path,
        number_of_orders=10,
        number_of_products=5,
        random_seed=3,
        include_invalid_rows=False,
    )
    order_path = tmp_path / "orders.csv"
    aliased_orders = pd.read_csv(order_path).rename(
        columns={"order_id": "Order Number", "quantity": "Qty"}
    )
    aliased_orders.to_csv(order_path, index=False)
    loaded = load_demo_files(tmp_path)

    result = DataProcessingPipeline().process(
        loaded["orders"],
        loaded["products"],
        loaded["inventory"],
        loaded["returns"],
    )

    assert result.targets.empty
    assert "reporting_month" in result.processed_orders
    assert DatasetType.MONTHLY_TARGETS not in result.source_metadata


def test_safe_merge_rejects_duplicate_dimension_keys() -> None:
    facts = pd.DataFrame({"product_id": ["P-1", "P-2"]})
    duplicated_dimension = pd.DataFrame(
        {"product_id": ["P-1", "P-1"], "name": ["One", "Duplicate"]}
    )

    with pytest.raises(DataValidationError, match="join keys are not unique"):
        safe_many_to_one_merge(
            facts,
            duplicated_dimension,
            on="product_id",
            right_name="products",
        )
