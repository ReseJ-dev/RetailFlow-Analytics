"""Typed application configuration loaded from defaults, YAML, and the environment."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from retailflow.common.exceptions import ConfigurationError


class ReportSettings(BaseModel):
    """Settings controlling management report content and presentation."""

    model_config = ConfigDict(extra="forbid")

    company_name: str = "RetailFlow Analytics"
    default_currency: str = "USD"
    date_format: str = "%Y-%m-%d"
    include_raw_data: bool = False
    include_quality_report: bool = True
    include_inventory_analysis: bool = True
    include_returns_analysis: bool = True
    include_recommendations: bool = True


class InventoryThresholds(BaseModel):
    """Coverage and inactivity thresholds used by inventory analysis."""

    model_config = ConfigDict(extra="forbid")

    critical_coverage_days: int = Field(default=7, ge=0)
    low_coverage_days: int = Field(default=21, ge=0)
    overstock_coverage_days: int = Field(default=90, ge=0)
    dead_stock_days: int = Field(default=180, ge=0)

    @model_validator(mode="after")
    def validate_coverage_order(self) -> "InventoryThresholds":
        """Ensure coverage bands progress from critical through overstock."""
        if not (
            self.critical_coverage_days
            < self.low_coverage_days
            < self.overstock_coverage_days
        ):
            raise ValueError(
                "coverage thresholds must satisfy critical_coverage_days "
                "< low_coverage_days < overstock_coverage_days"
            )
        return self


class ValidationSettings(BaseModel):
    """Settings controlling validation and invalid-row handling."""

    model_config = ConfigDict(extra="forbid")

    duplicate_strategy: Literal[
        "keep_first",
        "keep_latest",
        "exclude_all",
        "error",
        "keep_last",
        "remove_all",
    ] = "keep_first"
    allow_unknown_products: bool = False
    exclude_invalid_rows: bool = True
    allow_report_with_warnings_in_strict_mode: bool = False


class OutputSettings(BaseModel):
    """Settings controlling where generated reports will be written."""

    model_config = ConfigDict(extra="forbid")

    output_directory: Path = Path("output")
    filename_pattern: str = "retailflow_report_{timestamp}.xlsx"


class StorageSettings(BaseModel):
    """Settings controlling local run-history persistence."""

    model_config = ConfigDict(extra="forbid")

    database_url: str = "sqlite:///retailflow.sqlite3"
    create_tables: bool = True


class SourceSettings(BaseModel):
    """Explicit file or API source selection used by non-interactive runs."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["files", "api"] = "files"
    orders: Path | None = None
    products: Path | None = None
    inventory: Path | None = None
    returns: Path | None = None
    targets: Path | None = None
    api_url: str | None = None
    api_connect_timeout: float = Field(default=3.0, gt=0)
    api_read_timeout: float = Field(default=20.0, gt=0)
    api_retry_count: int = Field(default=3, ge=0)
    api_backoff_factor: float = Field(default=0.5, ge=0)
    api_page_size: int = Field(default=100, ge=1, le=500)
    allow_mixed_sources: bool = False


class RetailFlowSettings(BaseSettings):
    """Top-level RetailFlow Analytics application settings."""

    model_config = SettingsConfigDict(
        env_prefix="RETAILFLOW_",
        env_nested_delimiter="__",
        extra="forbid",
        validate_default=True,
    )

    report: ReportSettings = Field(default_factory=ReportSettings)
    inventory: InventoryThresholds = Field(default_factory=InventoryThresholds)
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    sources: SourceSettings = Field(default_factory=SourceSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Give environment variables precedence over values supplied by YAML."""
        del cls, settings_cls, dotenv_settings, file_secret_settings
        return env_settings, init_settings


def load_config(config_path: str | Path | None = None) -> RetailFlowSettings:
    """Load settings from defaults, an optional YAML file, and the environment.

    Environment variables use the ``RETAILFLOW_`` prefix and ``__`` between
    nested fields, for example ``RETAILFLOW_REPORT__DEFAULT_CURRENCY=EUR``.

    Raises:
        ConfigurationError: If the YAML file cannot be read or settings are invalid.
    """
    yaml_values: dict[str, Any] = {}
    if config_path is not None:
        path = Path(config_path)
        try:
            with path.open(encoding="utf-8") as config_file:
                loaded_values = yaml.safe_load(config_file)
        except OSError as error:
            raise ConfigurationError(
                f"Could not read the configuration file '{path}'.",
                technical_detail=str(error),
            ) from error
        except yaml.YAMLError as error:
            raise ConfigurationError(
                f"The configuration file '{path}' is not valid YAML.",
                technical_detail=str(error),
            ) from error

        if loaded_values is None:
            yaml_values = {}
        elif isinstance(loaded_values, dict):
            yaml_values = loaded_values
        else:
            raise ConfigurationError(
                f"The configuration file '{path}' must contain a mapping at its root.",
                technical_detail=f"Loaded YAML root type: {type(loaded_values).__name__}",
            )

    try:
        return RetailFlowSettings(**yaml_values)
    except ValidationError as error:
        raise ConfigurationError(
            "The application configuration contains invalid values.",
            technical_detail=str(error),
        ) from error
