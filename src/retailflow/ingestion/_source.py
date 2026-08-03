"""Internal helpers for normalizing ingestion sources."""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from retailflow.common.exceptions import DataSourceError
from retailflow.ingestion.models import FileSource

logger = logging.getLogger("retailflow.ingestion")


@dataclass(frozen=True)
class SourceContent:
    """Normalized binary source content and a safe display filename."""

    content: bytes
    filename: str


def source_filename(source: FileSource, explicit_filename: str | None = None) -> str | None:
    """Resolve a filename without reading source content."""
    if explicit_filename:
        return Path(explicit_filename).name
    if isinstance(source, (str, Path)):
        return Path(source).name
    candidate = getattr(source, "name", None)
    if isinstance(candidate, (str, Path)):
        return Path(candidate).name
    return None


def read_source(
    source: FileSource,
    *,
    filename: str | None = None,
    default_filename: str,
) -> SourceContent:
    """Read paths, binary values, and uploaded-file-like objects into bytes."""
    resolved_filename = source_filename(source, filename) or default_filename
    try:
        if isinstance(source, (str, Path)):
            content = Path(source).read_bytes()
        elif isinstance(source, bytes):
            content = source
        elif isinstance(source, (bytearray, memoryview)):
            content = bytes(source)
        else:
            content = _read_file_like(source)
    except OSError as error:
        logger.error("Could not read file %s: %s", resolved_filename, error)
        raise DataSourceError(
            f"The file '{resolved_filename}' could not be read.",
            technical_detail=str(error),
        ) from error
    except (TypeError, ValueError) as error:
        logger.error("Invalid file source %s: %s", resolved_filename, error)
        raise DataSourceError(
            "The uploaded file could not be read.",
            technical_detail=str(error),
        ) from error
    return SourceContent(content=content, filename=resolved_filename)


def _read_file_like(source: object) -> bytes:
    """Read an uploaded-file-like object while preserving its cursor when possible."""
    getvalue = getattr(source, "getvalue", None)
    if callable(getvalue):
        value = getvalue()
        if isinstance(value, bytes):
            return value

    read = getattr(source, "read", None)
    if not callable(read):
        raise TypeError("Expected a filesystem path, bytes, or a binary file-like object.")

    original_position: int | None = None
    tell = getattr(source, "tell", None)
    seek = getattr(source, "seek", None)
    if callable(tell):
        try:
            original_position = int(tell())
        except (OSError, TypeError, ValueError):
            original_position = None
    if callable(seek):
        with suppress(OSError, TypeError, ValueError):
            seek(0)

    value = read()
    if original_position is not None and callable(seek):
        with suppress(OSError, TypeError, ValueError):
            seek(original_position)
    if not isinstance(value, bytes):
        raise TypeError("The uploaded file must provide binary content.")
    return value
