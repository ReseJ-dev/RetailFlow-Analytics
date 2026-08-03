"""CSV file ingestion with delimiter and practical encoding detection."""

from __future__ import annotations

import csv
import logging
from io import StringIO

import pandas as pd

from retailflow.common.exceptions import DataSourceError, EmptyFileError
from retailflow.ingestion._source import read_source
from retailflow.ingestion.models import FileMetadata, FileSource, LoadedDataset

logger = logging.getLogger("retailflow.ingestion")


def _decode_csv(content: bytes, requested_encoding: str | None) -> tuple[str, str]:
    """Decode CSV bytes and return text with the encoding used."""
    candidates: tuple[str, ...]
    if requested_encoding is not None:
        candidates = (requested_encoding,)
    elif content.startswith((b"\xff\xfe", b"\xfe\xff")):
        candidates = ("utf-16",)
    elif content.startswith(b"\xef\xbb\xbf"):
        candidates = ("utf-8-sig",)
    else:
        candidates = ("utf-8", "cp1252")

    errors: list[str] = []
    for candidate in candidates:
        try:
            return content.decode(candidate), candidate
        except (LookupError, UnicodeDecodeError) as error:
            errors.append(f"{candidate}: {error}")

    detail = "; ".join(errors)
    logger.error("CSV decoding failed: %s", detail)
    raise DataSourceError(
        "The CSV file could not be decoded. Try selecting another encoding.",
        technical_detail=detail,
    )


def _detect_delimiter(text: str) -> str:
    """Detect a common delimiter, falling back to comma for one-column CSV files."""
    sample = text[:16_384]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def read_csv_file(
    source: FileSource,
    *,
    filename: str | None = None,
    encoding: str | None = None,
    delimiter: str | None = None,
) -> LoadedDataset:
    """Load a CSV source without applying business validation or cleaning."""
    source_content = read_source(source, filename=filename, default_filename="uploaded.csv")
    if not source_content.content or not source_content.content.strip():
        raise EmptyFileError("The uploaded file is empty.")

    text, detected_encoding = _decode_csv(source_content.content, encoding)
    detected_delimiter = delimiter or _detect_delimiter(text)
    try:
        dataframe = pd.read_csv(StringIO(text), sep=detected_delimiter, on_bad_lines="error")
    except pd.errors.EmptyDataError as error:
        logger.error("CSV %s contains no columns: %s", source_content.filename, error)
        raise DataSourceError(
            "The CSV file does not contain any columns.",
            technical_detail=str(error),
        ) from error
    except (csv.Error, pd.errors.ParserError, UnicodeError, ValueError) as error:
        logger.error("CSV %s could not be parsed: %s", source_content.filename, error)
        raise DataSourceError(
            "The CSV file could not be read because its structure is malformed.",
            technical_detail=str(error),
        ) from error

    if dataframe.columns.empty:
        raise DataSourceError("The CSV file does not contain any columns.")

    columns = tuple(str(column) for column in dataframe.columns)
    metadata = FileMetadata(
        filename=source_content.filename,
        file_type="csv",
        file_size=len(source_content.content),
        row_count=len(dataframe),
        column_count=len(columns),
        columns=columns,
        detected_delimiter=detected_delimiter,
        detected_encoding=detected_encoding,
    )
    return LoadedDataset(dataframe=dataframe, metadata=metadata)


read_csv = read_csv_file
