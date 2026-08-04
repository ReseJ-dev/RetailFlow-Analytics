"""Unit tests for the Typer command surface and stable failures."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from retailflow import __version__
from retailflow.cli import app
from retailflow.cli_helpers import ExitCode

runner = CliRunner()


def test_help_lists_commands_and_exit_codes() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == ExitCode.SUCCESS
    assert "generate-demo-data" in result.output
    assert "show-config" in result.output
    assert "Exit codes" in result.output


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == ExitCode.SUCCESS
    assert result.output.strip() == f"RetailFlow Analytics {__version__}"


def test_missing_required_sources_use_source_file_exit_without_traceback() -> None:
    result = runner.invoke(app, ["generate"])

    assert result.exit_code == ExitCode.SOURCE_FILE_ERROR
    assert "Required source files are missing" in result.output
    assert "Traceback" not in result.output


def test_nonexistent_required_file_uses_source_file_exit(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"

    result = runner.invoke(
        app,
        [
            "validate",
            "--orders",
            str(missing),
            "--products",
            str(missing),
            "--inventory",
            str(missing),
            "--returns",
            str(missing),
        ],
    )

    assert result.exit_code == ExitCode.SOURCE_FILE_ERROR
    assert "does not exist or is not readable" in result.output
    assert "Traceback" not in result.output


def test_invalid_configuration_uses_configuration_exit_code(tmp_path: Path) -> None:
    config = tmp_path / "invalid.yaml"
    config.write_text("inventory:\n  critical_coverage_days: -1\n", encoding="utf-8")

    result = runner.invoke(app, ["show-config", "--config", str(config)])

    assert result.exit_code == ExitCode.CONFIGURATION_ERROR
    assert "configuration contains invalid values" in result.output
    assert "Traceback" not in result.output


def test_debug_mode_shows_traceback_for_internal_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_config(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("unexpected test failure")

    monkeypatch.setattr("retailflow.cli.load_config", fail_config)

    result = runner.invoke(app, ["generate", "--debug"])

    assert result.exit_code == ExitCode.INTERNAL_ERROR
    assert "Traceback" in result.output
    assert "unexpected test failure" in result.output


def test_generate_demo_data_command_reuses_existing_generator(tmp_path: Path) -> None:
    destination = tmp_path / "demo"

    result = runner.invoke(
        app,
        [
            "generate-demo-data",
            "--output-directory",
            str(destination),
            "--number-of-orders",
            "20",
            "--number-of-products",
            "5",
            "--exclude-invalid-rows",
        ],
    )

    assert result.exit_code == ExitCode.SUCCESS
    assert (destination / "orders.csv").exists()
    assert (destination / "products.xlsx").exists()


def test_show_config_does_not_print_database_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = "sqlite:///history.sqlite3"
    monkeypatch.setenv("RETAILFLOW_STORAGE__DATABASE_URL", database_url)

    result = runner.invoke(app, ["show-config"])

    assert result.exit_code == ExitCode.SUCCESS
    assert database_url not in result.output
