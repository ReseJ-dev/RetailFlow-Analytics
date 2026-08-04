"""End-to-end CLI tests using real ingestion, processing, reporting, and history."""

from pathlib import Path

import pandas as pd
import yaml
from typer.testing import CliRunner

from retailflow.cli import app
from retailflow.cli_helpers import ExitCode
from retailflow.storage import Database, RunRepository, RunStatus

runner = CliRunner()


def _write_sources(directory: Path, *, warning: bool = False) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    orders = directory / "orders.csv"
    products = directory / "products.xlsx"
    inventory = directory / "inventory.csv"
    returns = directory / "returns.xlsx"
    targets = directory / "monthly_targets.csv"
    pd.DataFrame(
        {
            "order_id": ["O-1", "O-2"],
            "order_date": ["2025-01-05", "2025-01-15"],
            "product_id": ["P-1", "P-1"],
            "quantity": [2, 1],
            "unit_price": [10.0, 10.0],
            "discount": [0.0, 0.0],
            "currency": ["USD", "USD"],
            "order_status": ["completed", "completed"],
        }
    ).to_csv(orders, index=False)
    pd.DataFrame(
        {
            "product_id": ["P-1"],
            "product_name": ["Desk"],
            "category": ["Office"],
            "purchase_cost": [5.0],
            "recommended_price": [4.0 if warning else 10.0],
            "vat_rate": [0.2],
        }
    ).to_excel(products, index=False)
    pd.DataFrame(
        {
            "product_id": ["P-1"],
            "warehouse": ["Nicosia"],
            "stock_quantity": [20],
            "reserved_quantity": [0],
            "reorder_level": [5],
            "last_restock_date": ["2025-01-01"],
        }
    ).to_csv(inventory, index=False)
    pd.DataFrame(
        columns=(
            "return_id",
            "order_id",
            "product_id",
            "return_date",
            "quantity",
            "return_reason",
            "refund_amount",
        )
    ).to_excel(returns, index=False)
    pd.DataFrame(
        {
            "month": ["2025-01"],
            "revenue_target": [100.0],
            "profit_target": [50.0],
            "orders_target": [10],
        }
    ).to_csv(targets, index=False)
    return {
        "orders": orders,
        "products": products,
        "inventory": inventory,
        "returns": returns,
        "targets": targets,
    }


def _arguments(sources: dict[str, Path]) -> list[str]:
    arguments = ["generate"]
    for name, path in sources.items():
        arguments.extend((f"--{name}", str(path)))
    return arguments


def _environment(database_path: Path) -> dict[str, str]:
    return {"RETAILFLOW_STORAGE__DATABASE_URL": f"sqlite:///{database_path}"}


def test_valid_generation_prints_path_and_saves_completed_history(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path / "data")
    report = tmp_path / "reports" / "january.xlsx"
    database_path = tmp_path / "history.sqlite3"

    result = runner.invoke(
        app,
        [*_arguments(sources), "--period", "2025-01", "--output", str(report)],
        env=_environment(database_path),
    )

    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert report.exists()
    assert f"Report: {report.resolve()}" in result.output
    records = RunRepository(Database(f"sqlite:///{database_path}")).list_runs()
    assert len(records) == 1
    assert records[0].status is RunStatus.COMPLETED
    assert records[0].report_path == str(report.resolve())


def test_generate_supports_configuration_only(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path / "configured-data")
    database_path = tmp_path / "configured-history.sqlite3"
    output_directory = tmp_path / "configured-output"
    config = tmp_path / "retailflow.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "sources": {name: str(path) for name, path in sources.items()},
                "output": {
                    "output_directory": str(output_directory),
                    "filename_pattern": "configured_report.xlsx",
                },
                "storage": {"database_url": f"sqlite:///{database_path}"},
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["generate", "--config", str(config)])

    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert (output_directory / "configured_report.xlsx").exists()


def test_strict_warning_fails_without_creating_report(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path / "warning-data", warning=True)
    report = tmp_path / "strict.xlsx"

    result = runner.invoke(
        app,
        [*_arguments(sources), "--output", str(report), "--strict"],
        env=_environment(tmp_path / "strict-history.sqlite3"),
    )

    assert result.exit_code == ExitCode.VALIDATION_FAILURE
    assert "Strict mode found" in result.output
    assert not report.exists()
    assert "Traceback" not in result.output


def test_existing_output_without_overwrite_is_failed_and_recorded(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path / "existing-data")
    report = tmp_path / "existing.xlsx"
    database_path = tmp_path / "existing-history.sqlite3"
    arguments = [*_arguments(sources), "--output", str(report)]
    environment = _environment(database_path)
    first = runner.invoke(app, arguments, env=environment)
    assert first.exit_code == ExitCode.SUCCESS

    second = runner.invoke(app, arguments, env=environment)

    assert second.exit_code == ExitCode.REPORT_GENERATION_FAILURE
    assert "already exists" in second.output
    assert "Traceback" not in second.output
    records = RunRepository(Database(f"sqlite:///{database_path}")).list_runs()
    assert [record.status for record in records] == [RunStatus.FAILED, RunStatus.COMPLETED]


def test_validate_prints_counts_and_writes_only_error_report(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path / "validate-data")
    error_report = tmp_path / "quality.xlsx"
    arguments = ["validate"]
    for name, path in sources.items():
        arguments.extend((f"--{name}", str(path)))
    arguments.extend(("--error-report", str(error_report)))

    result = runner.invoke(app, arguments)

    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert "Source rows:" in result.output
    assert "Rule-based quality score:" in result.output
    assert error_report.exists()
    assert not (tmp_path / "retailflow_report.xlsx").exists()
