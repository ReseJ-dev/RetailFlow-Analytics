"""Dispatch supported tabular files to the appropriate ingestion reader."""

from __future__ import annotations

from pathlib import Path

from retailflow.common.exceptions import DataSourceError
from retailflow.ingestion._source import read_source, source_filename
from retailflow.ingestion.csv_reader import read_csv_file
from retailflow.ingestion.excel_reader import read_excel_file
from retailflow.ingestion.models import FileSource, LoadedDataset


def load_file(
    source: FileSource,
    *,
    filename: str | None = None,
    sheet_name: str | None = None,
    encoding: str | None = None,
    delimiter: str | None = None,
) -> LoadedDataset:
    """Load a CSV or XLSX file from a path, bytes, or uploaded-file-like object."""
    resolved_filename = source_filename(source, filename)
    if resolved_filename is not None:
        extension = Path(resolved_filename).suffix.lower()
        if extension == ".csv":
            return read_csv_file(
                source,
                filename=resolved_filename,
                encoding=encoding,
                delimiter=delimiter,
            )
        if extension == ".xlsx":
            return read_excel_file(source, filename=resolved_filename, sheet_name=sheet_name)
        raise DataSourceError(
            f"The file type '{extension or 'unknown'}' is not supported. "
            "Please select a CSV or XLSX file."
        )

    source_content = read_source(source, default_filename="uploaded")
    if source_content.content.startswith(b"PK\x03\x04"):
        return read_excel_file(
            source_content.content,
            filename="uploaded.xlsx",
            sheet_name=sheet_name,
        )
    return read_csv_file(
        source_content.content,
        filename="uploaded.csv",
        encoding=encoding,
        delimiter=delimiter,
    )
