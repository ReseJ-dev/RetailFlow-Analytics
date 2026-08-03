"""Unit tests for CSV and XLSX ingestion."""

from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from retailflow.common.exceptions import DataSourceError, EmptyFileError
from retailflow.ingestion.csv_reader import read_csv_file
from retailflow.ingestion.excel_reader import read_excel_file
from retailflow.ingestion.file_loader import load_file


def test_load_valid_csv_detects_metadata(tmp_path: Path) -> None:
    """CSV paths should load data and expose delimiter and encoding metadata."""
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id;quantity\nO-1;2\nO-2;3\n", encoding="utf-8")

    loaded = read_csv_file(csv_path)

    assert loaded.filename == "orders.csv"
    assert loaded.file_type == "csv"
    assert loaded.file_size == csv_path.stat().st_size
    assert loaded.row_count == 2
    assert loaded.column_count == 2
    assert loaded.columns == ("order_id", "quantity")
    assert loaded.detected_delimiter == ";"
    assert loaded.detected_encoding == "utf-8"


def test_load_valid_excel_detects_metadata(tmp_path: Path) -> None:
    """XLSX paths should load the first readable worksheet and its metadata."""
    excel_path = tmp_path / "products.xlsx"
    pd.DataFrame({"product_id": ["P-1"], "name": ["Desk"]}).to_excel(
        excel_path, index=False, sheet_name="Products"
    )

    loaded = read_excel_file(excel_path)

    assert loaded.filename == "products.xlsx"
    assert loaded.file_type == "xlsx"
    assert loaded.row_count == 1
    assert loaded.columns == ("product_id", "name")
    assert loaded.selected_sheet_name == "Products"
    assert loaded.detected_delimiter is None


def test_empty_csv_is_rejected() -> None:
    """Zero-byte CSV input should produce the documented friendly error."""
    with pytest.raises(EmptyFileError, match="^The uploaded file is empty\\.$"):
        read_csv_file(b"")


def test_malformed_csv_is_rejected() -> None:
    """Structurally malformed CSV input should not leak parser details to users."""
    malformed_csv = b'order_id,quantity\nO-1,"unterminated\n'

    with pytest.raises(DataSourceError, match="structure is malformed") as captured_error:
        read_csv_file(malformed_csv)

    assert captured_error.value.technical_detail is not None


def test_undecodable_csv_has_friendly_error() -> None:
    """Invalid text for a declared BOM should suggest selecting another encoding."""
    with pytest.raises(
        DataSourceError,
        match="^The CSV file could not be decoded. Try selecting another encoding\\.$",
    ) as captured_error:
        read_csv_file(b"\xff\xfe\x00")

    assert captured_error.value.technical_detail is not None


def test_unsupported_extension_is_rejected(tmp_path: Path) -> None:
    """The generic loader should accept only CSV and XLSX extensions."""
    unsupported_path = tmp_path / "orders.json"
    unsupported_path.write_text("{}", encoding="utf-8")

    with pytest.raises(DataSourceError, match="file type '.json' is not supported"):
        load_file(unsupported_path)


def test_workbook_with_multiple_sheets_selects_requested_sheet() -> None:
    """Callers should be able to select a worksheet by name."""
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        pd.DataFrame({"order_id": ["O-1"]}).to_excel(writer, index=False, sheet_name="Orders")
        pd.DataFrame({"product_id": ["P-1", "P-2"]}).to_excel(
            writer, index=False, sheet_name="Products"
        )

    loaded = read_excel_file(stream, filename="business.xlsx", sheet_name="Products")

    assert loaded.selected_sheet_name == "Products"
    assert loaded.row_count == 2
    assert loaded.columns == ("product_id",)


def test_load_csv_from_in_memory_byte_stream() -> None:
    """Binary streams should be accepted without changing the caller's cursor."""
    stream = BytesIO(b"product_id,stock\nP-1,12\n")
    stream.seek(5)

    loaded = load_file(stream, filename="inventory.csv")

    assert loaded.dataframe.to_dict(orient="records") == [{"product_id": "P-1", "stock": 12}]
    assert stream.tell() == 5


def test_load_uploaded_file_like_object() -> None:
    """Objects exposing a Streamlit-style name and byte value should load directly."""

    class UploadedFileStub(BytesIO):
        name = "targets.csv"

    uploaded_file = UploadedFileStub(b"month,revenue_target\n2025-01,100000\n")

    loaded = load_file(uploaded_file)

    assert loaded.filename == "targets.csv"
    assert loaded.row_count == 1


def test_corrupted_workbook_has_friendly_error() -> None:
    """Corrupted XLSX content should return the documented workbook error."""
    with pytest.raises(
        DataSourceError,
        match="^The selected Excel workbook does not contain readable worksheets\\.$",
    ) as captured_error:
        read_excel_file(b"not an xlsx workbook")

    assert captured_error.value.technical_detail is not None
