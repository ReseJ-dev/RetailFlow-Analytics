"""Safe mappings between persistence, domain, and JSON configuration values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from retailflow.storage.models import RunRecord, RunRecordORM, RunStatus

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "api_token",
    "token",
    "secret",
    "password",
    "credential",
    "authorization",
    "private_key",
    "database_url",
    "connection_string",
    "dsn",
)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_").replace(" ", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def sanitize_configuration(value: object) -> dict[str, JsonValue]:
    """Return a JSON-safe configuration mapping with secret-bearing keys removed."""
    sanitized = _sanitize(value)
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}


def _sanitize(value: object) -> JsonValue:
    if isinstance(value, BaseModel):
        return _sanitize(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _sanitize(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if not _is_sensitive_key(str(key)) and str(key).casefold() not in {"logo", "content"}
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_sanitize(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return _sanitize(value.value)
    if isinstance(value, bytes):
        return "[binary value removed]"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def run_to_domain(record: RunRecordORM) -> RunRecord:
    """Detach one ORM record into the immutable public domain model."""
    return RunRecord(
        run_id=record.run_id,
        started_at=record.started_at,
        completed_at=record.completed_at,
        status=RunStatus(record.status),
        reporting_period_start=record.reporting_period_start,
        reporting_period_end=record.reporting_period_end,
        source_filenames=dict(record.source_filenames),
        source_row_counts={key: int(value) for key, value in record.source_row_counts.items()},
        processed_row_count=record.processed_row_count,
        excluded_row_count=record.excluded_row_count,
        warning_count=record.warning_count,
        error_count=record.error_count,
        report_path=record.report_path,
        report_filename=record.report_filename,
        report_size=record.report_size,
        configuration_snapshot=dict(record.configuration_snapshot),
        application_version=record.application_version,
        failure_summary=record.failure_summary,
        duration_seconds=record.duration_seconds,
    )


__all__ = ["JsonValue", "run_to_domain", "sanitize_configuration"]
