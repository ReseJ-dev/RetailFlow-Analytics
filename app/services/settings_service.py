"""Safe settings presentation and session-override operations."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.state import SessionState, StateKey
from retailflow.common.config import RetailFlowSettings, load_config
from retailflow.common.exceptions import ConfigurationError


class SettingSource(StrEnum):
    """User-facing origins in configuration precedence order."""

    ENVIRONMENT = "Environment"
    YAML = "YAML"
    DEFAULT = "Default"
    SESSION = "Session override"


@dataclass(frozen=True, slots=True)
class SettingsView:
    """Effective non-secret settings and their display metadata."""

    settings: RetailFlowSettings
    sources: Mapping[str, SettingSource]
    api_url: str
    api_url_source: SettingSource
    api_token_configured: bool


@dataclass(frozen=True, slots=True)
class SettingsDraft:
    """Editable settings supported by the current session-based application behavior."""

    company_name: str
    default_currency: str
    date_format: str
    include_raw_data: bool
    include_quality_report: bool
    include_inventory_analysis: bool
    include_returns_analysis: bool
    include_recommendations: bool
    output_directory: str
    filename_pattern: str
    duplicate_strategy: str
    allow_unknown_products: bool
    exclude_invalid_rows: bool
    allow_report_with_warnings_in_strict_mode: bool
    critical_coverage_days: int
    low_coverage_days: int
    overstock_coverage_days: int
    dead_stock_days: int
    api_url: str


_EDITABLE_SECTIONS = ("report", "inventory", "validation", "output")
_IMPORT_OVERRIDE_KEYS = (
    "default_currency",
    "duplicate_strategy",
    "allow_unknown_products",
    "exclude_invalid_rows",
)


def _session_mapping(state: SessionState, key: StateKey) -> dict[str, object]:
    value = state[key.value]
    return dict(value) if isinstance(value, Mapping) else {}


def _effective_settings(state: SessionState, base: RetailFlowSettings) -> RetailFlowSettings:
    values = base.model_dump(mode="python")
    overrides = _session_mapping(state, StateKey.REPORT_SETTINGS)
    for section in _EDITABLE_SECTIONS:
        section_override = overrides.get(section)
        if isinstance(section_override, Mapping):
            current = values.get(section)
            merged = dict(current) if isinstance(current, Mapping) else {}
            merged.update(section_override)
            values[section] = merged
    try:
        return RetailFlowSettings.model_validate(values)
    except ValidationError:
        return base


def _setting_source(
    state: SessionState,
    section: str,
    field: str,
    *,
    yaml_fields: frozenset[str],
) -> SettingSource:
    overrides = _session_mapping(state, StateKey.REPORT_SETTINGS)
    section_value = overrides.get(section)
    if isinstance(section_value, Mapping) and field in section_value:
        return SettingSource.SESSION
    env_name = f"RETAILFLOW_{section.upper()}__{field.upper()}"
    if env_name in os.environ:
        return SettingSource.ENVIRONMENT
    path = f"{section}.{field}"
    if path in yaml_fields:
        return SettingSource.YAML
    return SettingSource.DEFAULT


def load_settings_view(
    state: SessionState,
    *,
    base: RetailFlowSettings | None = None,
    yaml_fields: frozenset[str] = frozenset(),
) -> SettingsView:
    """Load effective values without changing normal config precedence or exposing secrets."""
    configured = base or load_config()
    effective = _effective_settings(state, configured)
    sources = {
        f"{section}.{field}": _setting_source(
            state,
            section,
            field,
            yaml_fields=yaml_fields,
        )
        for section in (*_EDITABLE_SECTIONS, "storage", "sources")
        for field in type(getattr(effective, section)).model_fields
    }
    imports = _session_mapping(state, StateKey.IMPORT_SETTINGS)
    if "api_url" in imports:
        api_source = SettingSource.SESSION
        api_url = str(imports["api_url"])
    elif "RETAIL_API_URL" in os.environ:
        api_source = SettingSource.ENVIRONMENT
        api_url = os.environ["RETAIL_API_URL"]
    elif "RETAILFLOW_SOURCES__API_URL" in os.environ:
        api_source = SettingSource.ENVIRONMENT
        api_url = str(effective.sources.api_url or "")
    else:
        api_source = (
            SettingSource.YAML
            if "sources.api_url" in yaml_fields
            else SettingSource.DEFAULT
        )
        api_url = str(effective.sources.api_url or "")
    return SettingsView(
        effective,
        sources,
        api_url,
        api_source,
        api_token_configured=bool(os.getenv("RETAIL_API_TOKEN")),
    )


def draft_from_view(view: SettingsView) -> SettingsDraft:
    """Create editable values from the effective typed configuration."""
    settings = view.settings
    return SettingsDraft(
        company_name=settings.report.company_name,
        default_currency=settings.report.default_currency,
        date_format=settings.report.date_format,
        include_raw_data=settings.report.include_raw_data,
        include_quality_report=settings.report.include_quality_report,
        include_inventory_analysis=settings.report.include_inventory_analysis,
        include_returns_analysis=settings.report.include_returns_analysis,
        include_recommendations=settings.report.include_recommendations,
        output_directory=str(settings.output.output_directory),
        filename_pattern=settings.output.filename_pattern,
        duplicate_strategy=settings.validation.duplicate_strategy,
        allow_unknown_products=settings.validation.allow_unknown_products,
        exclude_invalid_rows=settings.validation.exclude_invalid_rows,
        allow_report_with_warnings_in_strict_mode=(
            settings.validation.allow_report_with_warnings_in_strict_mode
        ),
        critical_coverage_days=settings.inventory.critical_coverage_days,
        low_coverage_days=settings.inventory.low_coverage_days,
        overstock_coverage_days=settings.inventory.overstock_coverage_days,
        dead_stock_days=settings.inventory.dead_stock_days,
        api_url=view.api_url,
    )


def validate_settings_draft(
    draft: SettingsDraft,
    *,
    base: RetailFlowSettings | None = None,
) -> RetailFlowSettings:
    """Validate one session draft, including strict inventory-threshold ordering."""
    values = (base or load_config()).model_dump(mode="python")
    values["report"] = {
        "company_name": draft.company_name.strip(),
        "default_currency": draft.default_currency.strip().upper(),
        "date_format": draft.date_format.strip(),
        "include_raw_data": draft.include_raw_data,
        "include_quality_report": draft.include_quality_report,
        "include_inventory_analysis": draft.include_inventory_analysis,
        "include_returns_analysis": draft.include_returns_analysis,
        "include_recommendations": draft.include_recommendations,
    }
    values["inventory"] = {
        "critical_coverage_days": draft.critical_coverage_days,
        "low_coverage_days": draft.low_coverage_days,
        "overstock_coverage_days": draft.overstock_coverage_days,
        "dead_stock_days": draft.dead_stock_days,
    }
    values["validation"] = {
        "duplicate_strategy": draft.duplicate_strategy,
        "allow_unknown_products": draft.allow_unknown_products,
        "exclude_invalid_rows": draft.exclude_invalid_rows,
        "allow_report_with_warnings_in_strict_mode": (
            draft.allow_report_with_warnings_in_strict_mode
        ),
    }
    values["output"] = {
        "output_directory": draft.output_directory.strip(),
        "filename_pattern": draft.filename_pattern.strip(),
    }
    try:
        return RetailFlowSettings.model_validate(values)
    except ValidationError as error:
        raise ConfigurationError(
            "These settings contain invalid values. Review the highlighted guidance.",
            technical_detail=str(error),
        ) from error


def apply_session_settings(
    state: SessionState,
    draft: SettingsDraft,
    *,
    base: RetailFlowSettings | None = None,
) -> RetailFlowSettings:
    """Apply validated overrides to existing non-persistent session-state settings."""
    validated = validate_settings_draft(draft, base=base)
    report_state = _session_mapping(state, StateKey.REPORT_SETTINGS)
    for section in _EDITABLE_SECTIONS:
        report_state[section] = getattr(validated, section).model_dump(mode="python")
    state[StateKey.REPORT_SETTINGS.value] = report_state

    import_state = _session_mapping(state, StateKey.IMPORT_SETTINGS)
    import_state.update(
        {
            "default_currency": validated.report.default_currency,
            "duplicate_strategy": validated.validation.duplicate_strategy,
            "allow_unknown_products": validated.validation.allow_unknown_products,
            "exclude_invalid_rows": validated.validation.exclude_invalid_rows,
        }
    )
    import_state.pop("api_token", None)
    import_state.pop("token", None)
    state[StateKey.IMPORT_SETTINGS.value] = import_state
    return validated


def reset_session_settings(state: SessionState, *, confirmed: bool) -> None:
    """Remove only settings-page overrides after explicit user confirmation."""
    if not confirmed:
        raise ConfigurationError("Confirm the reset before removing session overrides.")
    report_state = _session_mapping(state, StateKey.REPORT_SETTINGS)
    for section in _EDITABLE_SECTIONS:
        report_state.pop(section, None)
    state[StateKey.REPORT_SETTINGS.value] = report_state
    import_state = _session_mapping(state, StateKey.IMPORT_SETTINGS)
    for key in _IMPORT_OVERRIDE_KEYS:
        import_state.pop(key, None)
    import_state.pop("api_token", None)
    import_state.pop("token", None)
    state[StateKey.IMPORT_SETTINGS.value] = import_state


def mask_database_url(database_url: str) -> str:
    """Render a database URL with any embedded password hidden."""
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        return "Configured database connection"


__all__ = [
    "SettingSource",
    "SettingsDraft",
    "SettingsView",
    "apply_session_settings",
    "draft_from_view",
    "load_settings_view",
    "mask_database_url",
    "reset_session_settings",
    "validate_settings_draft",
]
