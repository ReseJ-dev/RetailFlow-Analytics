"""Typer command-line interface for RetailFlow Analytics."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Annotated

import typer
import yaml

from retailflow import __version__
from retailflow.cli_helpers import (
    CliValidationError,
    calculate_analytics,
    ensure_generation_allowed,
    exception_exit_code,
    generate_report,
    load_configured_datasets,
    parse_reporting_period,
    process_loaded_datasets,
    validation_summary,
    write_validation_report,
)
from retailflow.common.config import RetailFlowSettings, load_config
from retailflow.common.exceptions import ConfigurationError, RetailFlowError
from retailflow.models import ProcessingProgress
from retailflow.storage.mappers import sanitize_configuration

_EXIT_CODE_HELP = (
    "Exit codes: 0 success; 2 configuration error; 3 source-file error; "
    "4 validation failure; 5 report-generation failure; 10 unexpected internal error."
)

app = typer.Typer(
    name="retailflow",
    help="Validate RetailFlow data and generate management reports.",
    epilog=_EXIT_CODE_HELP,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _settings(config: Path | None, currency: str | None = None) -> RetailFlowSettings:
    settings = load_config(config)
    if currency is None:
        return settings
    normalized = currency.upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ConfigurationError("Currency must be a three-letter code such as EUR or USD.")
    return settings.model_copy(
        update={
            "report": settings.report.model_copy(update={"default_currency": normalized})
        }
    )


def _stage(message: str) -> None:
    typer.echo(f"[stage] {message}")


def _pipeline_stage(progress: ProcessingProgress) -> None:
    _stage(progress.message)


def _fail(error: BaseException, *, debug: bool) -> None:
    code = exception_exit_code(error)
    if debug:
        traceback.print_exception(error, file=sys.stderr)
    if isinstance(error, RetailFlowError):
        message = error.message
    else:
        message = "RetailFlow encountered an unexpected internal error."
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=int(code))


@app.command("generate")
def generate_command(
    orders: Annotated[Path | None, typer.Option("--orders", help="Orders CSV/XLSX.")] = None,
    products: Annotated[
        Path | None, typer.Option("--products", help="Products CSV/XLSX.")
    ] = None,
    inventory: Annotated[
        Path | None, typer.Option("--inventory", help="Inventory CSV/XLSX.")
    ] = None,
    returns: Annotated[
        Path | None, typer.Option("--returns", help="Returns CSV/XLSX.")
    ] = None,
    targets: Annotated[
        Path | None, typer.Option("--targets", help="Optional monthly targets CSV/XLSX.")
    ] = None,
    period: Annotated[
        str | None,
        typer.Option("--period", help="YYYY-MM or YYYY-MM-DD:YYYY-MM-DD."),
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Output XLSX path or directory.")
    ] = None,
    config: Annotated[
        Path | None, typer.Option("--config", help="Application YAML configuration.")
    ] = None,
    currency: Annotated[
        str | None, typer.Option("--currency", help="Three-letter report currency.")
    ] = None,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Allow replacing an existing report.")
    ] = False,
    strict: Annotated[
        bool, typer.Option("--strict", help="Treat validation warnings as failure.")
    ] = False,
    debug: Annotated[
        bool, typer.Option("--debug", help="Show tracebacks for troubleshooting.")
    ] = False,
) -> None:
    """Validate, analyse, persist, and generate an Excel management report."""
    try:
        settings = _settings(config, currency)
        _stage("Loading configured data source")
        datasets = load_configured_datasets(
            settings,
            orders=orders,
            products=products,
            inventory=inventory,
            returns=returns,
            targets=targets,
        )
        _stage("Running validation and processing pipeline")
        processing = process_loaded_datasets(
            datasets, settings, progress_callback=_pipeline_stage
        )
        strict_failure_after_report = ensure_generation_allowed(
            processing, settings, strict=strict
        )
        reporting_period = parse_reporting_period(period, processing)
        _stage("Calculating analytics")
        analytics = calculate_analytics(processing, reporting_period, settings)
        generated = generate_report(
            processing,
            analytics,
            reporting_period,
            settings,
            output=output,
            currency=currency,
            overwrite=overwrite,
            strict=strict,
            stage_callback=_stage,
        )
        typer.echo(
            f"Processed {generated.validation.source_rows:,} source rows; "
            f"{generated.validation.warnings} warning(s), "
            f"{generated.validation.errors} error(s)."
        )
        typer.echo(f"Report: {generated.report.report_path}")
        typer.echo(f"Run ID: {generated.run_id}")
        if strict_failure_after_report:
            raise CliValidationError(
                "Strict mode found warnings. The report was generated because configuration "
                "explicitly allows it."
            )
    except typer.Exit:
        raise
    except BaseException as error:
        _fail(error, debug=debug)


@app.command("validate")
def validate_command(
    orders: Annotated[Path | None, typer.Option("--orders")] = None,
    products: Annotated[Path | None, typer.Option("--products")] = None,
    inventory: Annotated[Path | None, typer.Option("--inventory")] = None,
    returns: Annotated[Path | None, typer.Option("--returns")] = None,
    targets: Annotated[Path | None, typer.Option("--targets")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    error_report: Annotated[
        Path | None,
        typer.Option("--error-report", help="Optional validation-only XLSX output."),
    ] = None,
    debug: Annotated[bool, typer.Option("--debug")] = False,
) -> None:
    """Validate source files without generating the management workbook."""
    try:
        settings = _settings(config)
        _stage("Loading configured data source")
        datasets = load_configured_datasets(
            settings,
            orders=orders,
            products=products,
            inventory=inventory,
            returns=returns,
            targets=targets,
        )
        _stage("Running validation and processing pipeline")
        processing = process_loaded_datasets(
            datasets, settings, progress_callback=_pipeline_stage
        )
        summary = validation_summary(processing)
        typer.echo(f"Source rows: {summary.source_rows:,}")
        typer.echo(f"Processed rows: {summary.processed_rows:,}")
        typer.echo(f"Excluded rows: {summary.excluded_rows:,}")
        typer.echo(f"Warnings: {summary.warnings}")
        typer.echo(f"Errors: {summary.errors}")
        typer.echo(f"Rule-based quality score: {summary.quality_score:.2f}%")
        if error_report is not None:
            path = write_validation_report(processing, error_report, settings)
            typer.echo(f"Error report: {path}")
        if any(
            issue.severity.value == "error" and not issue.row_can_continue
            for issue in processing.validation_issues
        ):
            raise CliValidationError("Validation found blocking errors.")
    except typer.Exit:
        raise
    except BaseException as error:
        _fail(error, debug=debug)


@app.command("generate-demo-data")
def generate_demo_data_command(
    output_directory: Annotated[
        Path, typer.Option("--output-directory", "--output-dir")
    ] = Path("demo_data"),
    number_of_orders: Annotated[
        int, typer.Option("--number-of-orders", "--num-orders", min=1)
    ] = 5_000,
    number_of_products: Annotated[
        int, typer.Option("--number-of-products", "--num-products", min=1)
    ] = 200,
    random_seed: Annotated[int, typer.Option("--random-seed", "--seed")] = 42,
    include_invalid_rows: Annotated[
        bool, typer.Option("--include-invalid-rows/--exclude-invalid-rows")
    ] = True,
    debug: Annotated[bool, typer.Option("--debug")] = False,
) -> None:
    """Generate reproducible demonstration source files."""
    try:
        from scripts.generate_demo_data import generate_demo_data

        summary = generate_demo_data(
            output_directory,
            number_of_orders,
            number_of_products,
            random_seed,
            include_invalid_rows,
        )
        typer.echo(
            f"Generated {summary.orders:,} orders and {summary.products:,} products "
            f"in '{summary.output_directory}'."
        )
    except (OSError, ValueError) as error:
        _fail(ConfigurationError(str(error), technical_detail=repr(error)), debug=debug)
    except BaseException as error:
        _fail(error, debug=debug)


@app.command("show-config")
def show_config_command(
    config: Annotated[Path | None, typer.Option("--config")] = None,
    debug: Annotated[bool, typer.Option("--debug")] = False,
) -> None:
    """Display effective configuration with secrets removed."""
    try:
        settings = _settings(config)
        typer.echo(yaml.safe_dump(sanitize_configuration(settings), sort_keys=False).rstrip())
    except BaseException as error:
        _fail(error, debug=debug)


@app.command("version")
def version_command() -> None:
    """Print the installed RetailFlow Analytics version."""
    typer.echo(f"RetailFlow Analytics {__version__}")


__all__ = ["app"]
