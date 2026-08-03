"""Shared XlsxWriter formats and worksheet table helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
from xlsxwriter.format import Format
from xlsxwriter.workbook import Workbook
from xlsxwriter.worksheet import Worksheet

from retailflow.transformation.normalizer import is_missing

_TABLE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_]")


@dataclass(frozen=True, slots=True)
class ReportFormats:
    """Consistent workbook formats shared by every report worksheet."""

    title: Format
    subtitle: Format
    section_header: Format
    label: Format
    text: Format
    currency: Format
    percentage: Format
    percentage_points: Format
    integer: Format
    decimal: Format
    date: Format
    datetime: Format
    warning: Format
    error: Format
    success: Format
    note: Format


def create_report_formats(workbook: Workbook, currency_code: str = "USD") -> ReportFormats:
    """Create the workbook's standard visual and number formats."""
    currency_pattern = f'#,##0.00 "{currency_code}";[Red]-#,##0.00 "{currency_code}"'
    return ReportFormats(
        title=workbook.add_format(
            {"bold": True, "font_size": 20, "font_color": "#17365D", "bottom": 2}
        ),
        subtitle=workbook.add_format(
            {"bold": True, "font_size": 12, "font_color": "#4F81BD"}
        ),
        section_header=workbook.add_format(
            {
                "bold": True,
                "font_color": "#FFFFFF",
                "bg_color": "#1F4E78",
                "border": 1,
            }
        ),
        label=workbook.add_format({"bold": True, "font_color": "#17365D"}),
        text=workbook.add_format({"valign": "top"}),
        currency=workbook.add_format({"num_format": currency_pattern}),
        percentage=workbook.add_format({"num_format": "0.00%"}),
        percentage_points=workbook.add_format({"num_format": '0.00"%"'}),
        integer=workbook.add_format({"num_format": "#,##0"}),
        decimal=workbook.add_format({"num_format": "#,##0.00"}),
        date=workbook.add_format({"num_format": "yyyy-mm-dd"}),
        datetime=workbook.add_format({"num_format": "yyyy-mm-dd hh:mm:ss"}),
        warning=workbook.add_format(
            {"bg_color": "#FFF2CC", "font_color": "#7F6000", "border": 1}
        ),
        error=workbook.add_format(
            {"bg_color": "#F4CCCC", "font_color": "#9C0006", "border": 1}
        ),
        success=workbook.add_format(
            {"bg_color": "#D9EAD3", "font_color": "#274E13", "border": 1}
        ),
        note=workbook.add_format(
            {"italic": True, "font_color": "#666666", "text_wrap": True}
        ),
    )


def write_title(worksheet: Worksheet, title: str, formats: ReportFormats) -> None:
    """Write a standard worksheet title without using merged cells."""
    worksheet.write(0, 0, title, formats.title)
    worksheet.set_row(0, 28)


def write_section_header(
    worksheet: Worksheet,
    row: int,
    title: str,
    formats: ReportFormats,
    *,
    width: int = 4,
) -> None:
    """Write a section heading across individually formatted cells."""
    worksheet.write(row, 0, title, formats.section_header)
    for column in range(1, width):
        worksheet.write_blank(row, column, None, formats.section_header)


def _column_format(column_name: str, formats: ReportFormats) -> Format | None:
    """Choose a display format from a canonical column name."""
    name = column_name.casefold()
    if name.endswith("_percent") or "margin_percent" in name:
        return formats.percentage_points
    if name in {"discount", "vat_rate"}:
        return formats.percentage
    if "date" in name or name in {"day", "week"}:
        return formats.date
    if any(
        token in name
        for token in ("revenue", "amount", "price", "cost", "profit", "refund")
    ):
        return formats.currency
    if any(
        token in name
        for token in ("quantity", "orders", "units", "row_count", "rows", "count")
    ):
        return formats.integer
    if any(token in name for token in ("coverage", "average", "rate")):
        return formats.decimal
    return None


def _excel_value(value: object) -> object | None:
    """Convert pandas, Decimal, and structured values into XlsxWriter values."""
    if is_missing(value):
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, pd.Timestamp):
        timestamp = value
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC").tz_localize(None)
        return timestamp.to_pydatetime()
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    if isinstance(value, dict | list | tuple | set | frozenset):
        return json.dumps(value, default=str, sort_keys=True)
    item = getattr(value, "item", None)
    if callable(item):
        converted: object = item()
        return converted
    return value


def _table_name(name: str) -> str:
    """Return a valid Excel table identifier."""
    normalized = _TABLE_NAME_PATTERN.sub("_", name)
    if not normalized or normalized[0].isdigit():
        normalized = f"Table_{normalized}"
    return normalized[:250]


def _supports_total(column_name: str) -> bool:
    """Return whether summing a column is meaningful in a report table."""
    name = column_name.casefold()
    return any(
        token in name
        for token in ("revenue", "amount", "profit", "cost", "quantity", "orders", "units")
    ) and not any(token in name for token in ("average", "margin", "rate"))


def write_dataframe_table(
    worksheet: Worksheet,
    dataframe: pd.DataFrame,
    start_row: int,
    start_column: int,
    formats: ReportFormats,
    table_name: str,
    *,
    include_totals: bool = False,
    freeze_at: tuple[int, int] | None = None,
) -> int:
    """Write a DataFrame as a styled Excel table and return the next free row."""
    columns = [str(column) for column in dataframe.columns]
    if not columns:
        worksheet.write(start_row, start_column, "No columns available", formats.note)
        return start_row + 2

    if dataframe.empty:
        worksheet.write_row(start_row, start_column, columns, formats.section_header)
        worksheet.write(start_row + 1, start_column, "No data available", formats.note)
        for offset, column in enumerate(columns):
            worksheet.set_column(
                start_column + offset,
                start_column + offset,
                min(40, max(12, len(column) + 2)),
            )
        if freeze_at is not None:
            worksheet.freeze_panes(*freeze_at)
        return start_row + 3

    for row_offset, values in enumerate(dataframe.itertuples(index=False, name=None), start=1):
        for column_offset, value in enumerate(values):
            column_name = columns[column_offset]
            worksheet.write(
                start_row + row_offset,
                start_column + column_offset,
                _excel_value(value),
                _column_format(column_name, formats),
            )

    last_data_row = start_row + len(dataframe)
    last_table_row = last_data_row + int(include_totals)
    table_columns: list[dict[str, object]] = []
    for index, column in enumerate(columns):
        definition: dict[str, object] = {"header": column}
        column_format = _column_format(column, formats)
        if column_format is not None:
            definition["format"] = column_format
        if include_totals and _supports_total(column):
            definition["total_function"] = "sum"
        elif include_totals and index == 0:
            definition["total_string"] = "Total"
        table_columns.append(definition)
    worksheet.add_table(
        start_row,
        start_column,
        last_table_row,
        start_column + len(columns) - 1,
        {
            "name": _table_name(table_name),
            "columns": table_columns,
            "total_row": include_totals,
            "style": "Table Style Medium 2",
        },
    )

    for offset, column in enumerate(columns):
        sample_lengths = [len(str(value)) for value in dataframe.iloc[:, offset].head(100)]
        width = min(40, max([len(column) + 2, 12, *sample_lengths]))
        worksheet.set_column(start_column + offset, start_column + offset, width)
    if freeze_at is not None:
        worksheet.freeze_panes(*freeze_at)
    return last_table_row + 3


def write_key_values(
    worksheet: Worksheet,
    rows: list[tuple[str, object]],
    start_row: int,
    formats: ReportFormats,
) -> int:
    """Write labeled values and return the next free row."""
    for offset, (label, value) in enumerate(rows):
        row = start_row + offset
        worksheet.write(row, 0, label, formats.label)
        converted = _excel_value(value)
        value_format: Format | None = None
        if isinstance(value, datetime):
            value_format = formats.datetime
        elif isinstance(value, date):
            value_format = formats.date
        elif isinstance(value, int) and not isinstance(value, bool):
            value_format = formats.integer
        worksheet.write(row, 1, converted, value_format)
    worksheet.set_column(0, 0, 28)
    worksheet.set_column(1, 1, 32)
    return start_row + len(rows)
