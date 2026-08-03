"""Tests for typed application configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from retailflow.common.config import InventoryThresholds, load_config
from retailflow.common.exceptions import ConfigurationError


def test_load_config_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default configuration should be useful without a YAML file."""
    monkeypatch.delenv("RETAILFLOW_REPORT__COMPANY_NAME", raising=False)

    settings = load_config()

    assert settings.report.company_name == "RetailFlow Analytics"
    assert settings.inventory.critical_coverage_days == 7
    assert settings.output.output_directory == Path("output")


def test_load_config_reads_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Values in a YAML file should replace model defaults."""
    monkeypatch.delenv("RETAILFLOW_REPORT__COMPANY_NAME", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "report:\n  company_name: YAML Retail Ltd\n  default_currency: GBP\n",
        encoding="utf-8",
    )

    settings = load_config(config_path)

    assert settings.report.company_name == "YAML Retail Ltd"
    assert settings.report.default_currency == "GBP"
    assert settings.report.include_quality_report is True


def test_environment_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nested RetailFlow environment variables should have highest precedence."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "report:\n  company_name: YAML Retail Ltd\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RETAILFLOW_REPORT__COMPANY_NAME", "Environment Retail Ltd")
    monkeypatch.setenv("RETAILFLOW_REPORT__INCLUDE_RAW_DATA", "true")

    settings = load_config(config_path)

    assert settings.report.company_name == "Environment Retail Ltd"
    assert settings.report.include_raw_data is True


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("critical_coverage_days", -1),
        ("dead_stock_days", -1),
    ],
)
def test_inventory_thresholds_reject_negative_values(
    field_name: str, invalid_value: int
) -> None:
    """Day thresholds cannot be negative."""
    with pytest.raises(ValidationError):
        InventoryThresholds(**{field_name: invalid_value})


def test_inventory_thresholds_reject_invalid_order() -> None:
    """Coverage bands must be strictly ordered."""
    with pytest.raises(ValidationError, match="coverage thresholds must satisfy"):
        InventoryThresholds(
            critical_coverage_days=30,
            low_coverage_days=20,
            overstock_coverage_days=90,
        )


def test_load_config_wraps_validation_errors(tmp_path: Path) -> None:
    """Configuration callers should receive a safe application exception."""
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text(
        "inventory:\n  critical_coverage_days: -1\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as captured_error:
        load_config(config_path)

    assert str(captured_error.value) == "The application configuration contains invalid values."
    assert captured_error.value.technical_detail is not None
