"""XLSX workbook ingestion with sheet selection and metadata detection."""

from __future__ import annotations

import logging
from io import BytesIO

import pandas as pd

from retailflow.common.exceptions import DataSourceError, EmptyFileError
from retailflow.ingestion._source import read_source
from retailflow.ingestion.models import FileMetadata, FileSource, LoadedDataset

logger = logging.getLogger("retailflow.ingestion")

_NO_READABLE_WORKSHEETS = "The selected Excel workbook does not contain readable worksheets."


def _read_selected_sheet(
    workbook: pd.ExcelFile,
    sheet_name: str | None,
) -> tuple[pd.DataFrame, str]:
    """Read an explicit sheet or find the workbook's first sheet with columns."""
    if sheet_name is not None:
        if sheet_name not in workbook.sheet_names:
            raise DataSourceError(
                f"The Excel workbook does not contain a sheet named '{sheet_name}'."
            )
        dataframe = workbook.parse(sheet_name=sheet_name)
        if dataframe.columns.empty:
            raise DataSourceError("The selected Excel worksheet does not contain any columns.")
        return dataframe, sheet_name

    for candidate in workbook.sheet_names:
        try:
            dataframe = workbook.parse(sheet_name=candidate)
        except (ValueError, TypeError):
            continue
        if not dataframe.columns.empty:
            return dataframe, str(candidate)
    raise DataSourceError(_NO_READABLE_WORKSHEETS)


def read_excel_file(
    source: FileSource,
    *,
    filename: str | None = None,
    sheet_name: str | None = None,
) -> LoadedDataset:
    """Load one worksheet from an XLSX source without validating business data."""
    source_content = read_source(source, filename=filename, default_filename="uploaded.xlsx")
    if not source_content.content:
        raise EmptyFileError("The uploaded file is empty.")

    try:
        with pd.ExcelFile(BytesIO(source_content.content), engine="openpyxl") as workbook:
            if not workbook.sheet_names:
                raise DataSourceError(_NO_READABLE_WORKSHEETS)
            dataframe, selected_sheet = _read_selected_sheet(workbook, sheet_name)
    except DataSourceError:
        raise
    except Exception as error:
        logger.error("Excel workbook %s could not be read: %s", source_content.filename, error)
        raise DataSourceError(
            _NO_READABLE_WORKSHEETS,
            technical_detail=str(error),
        ) from error

    columns = tuple(str(column) for column in dataframe.columns)
    metadata = FileMetadata(
        filename=source_content.filename,
        file_type="xlsx",
        file_size=len(source_content.content),
        row_count=len(dataframe),
        column_count=len(columns),
        columns=columns,
        selected_sheet_name=selected_sheet,
    )
    return LoadedDataset(dataframe=dataframe, metadata=metadata)


read_excel = read_excel_file
