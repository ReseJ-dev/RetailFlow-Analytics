"""Models shared by CSV and Excel ingestion."""

from pathlib import Path
from typing import BinaryIO, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

type FileSource = str | Path | bytes | bytearray | memoryview | BinaryIO


class FileMetadata(BaseModel):
    """Metadata detected while loading a tabular file."""

    model_config = ConfigDict(frozen=True)

    filename: str
    file_type: Literal["csv", "xlsx", "api"]
    file_size: int = Field(ge=0)
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=1)
    columns: tuple[str, ...]
    selected_sheet_name: str | None = None
    detected_delimiter: str | None = None
    detected_encoding: str | None = None


class LoadedDataset(BaseModel):
    """A loaded pandas DataFrame together with its detected file metadata."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    dataframe: pd.DataFrame
    metadata: FileMetadata

    @property
    def data(self) -> pd.DataFrame:
        """Return the loaded DataFrame using a concise compatibility alias."""
        return self.dataframe

    @property
    def filename(self) -> str:
        """Return the source filename."""
        return self.metadata.filename

    @property
    def file_type(self) -> Literal["csv", "xlsx", "api"]:
        """Return the detected file type."""
        return self.metadata.file_type

    @property
    def file_size(self) -> int:
        """Return the source size in bytes."""
        return self.metadata.file_size

    @property
    def row_count(self) -> int:
        """Return the number of loaded data rows."""
        return self.metadata.row_count

    @property
    def column_count(self) -> int:
        """Return the number of detected columns."""
        return self.metadata.column_count

    @property
    def columns(self) -> tuple[str, ...]:
        """Return detected column names."""
        return self.metadata.columns

    @property
    def selected_sheet_name(self) -> str | None:
        """Return the selected Excel sheet, if applicable."""
        return self.metadata.selected_sheet_name

    @property
    def sheet_name(self) -> str | None:
        """Return the selected Excel sheet using a concise compatibility alias."""
        return self.selected_sheet_name

    @property
    def detected_delimiter(self) -> str | None:
        """Return the detected CSV delimiter, if applicable."""
        return self.metadata.detected_delimiter

    @property
    def delimiter(self) -> str | None:
        """Return the CSV delimiter using a concise compatibility alias."""
        return self.detected_delimiter

    @property
    def detected_encoding(self) -> str | None:
        """Return the detected text encoding, if applicable."""
        return self.metadata.detected_encoding

    @property
    def encoding(self) -> str | None:
        """Return the text encoding using a concise compatibility alias."""
        return self.detected_encoding
