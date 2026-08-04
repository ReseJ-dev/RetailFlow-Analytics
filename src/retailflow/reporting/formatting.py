"""Central visual theme, formats, and layout helpers for Excel reports."""

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
class ReportTheme:
    """Reusable restrained colour, typography, and spacing system."""

    primary: str = "#17365D"
    primary_light: str = "#D9E5F2"
    accent: str = "#4472C4"
    positive: str = "#70AD47"
    positive_light: str = "#E2F0D9"
    warning: str = "#ED7D31"
    warning_light: str = "#FCE4D6"
    error: str = "#C00000"
    error_light: str = "#F4CCCC"
    neutral: str = "#7F8C8D"
    neutral_light: str = "#E7E6E6"
    background: str = "#F3F6F8"
    white: str = "#FFFFFF"
    text: str = "#243447"
    font_name: str = "Aptos"
    title_row_height: int = 30
    section_row_height: int = 22
    body_row_height: int = 18


DEFAULT_THEME = ReportTheme()


@dataclass(frozen=True, slots=True)
class ReportVisualThresholds:
    """Presentation-only thresholds used for conditional formatting."""

    low_gross_margin_percent: float = 10.0
    high_return_rate_percent: float = 10.0
    close_to_target_ratio: float = 0.9
    exceeded_target_ratio: float = 1.05

    def __post_init__(self) -> None:
        if not 0 <= self.low_gross_margin_percent <= 100:
            raise ValueError("low gross-margin threshold must be between 0 and 100")
        if not 0 <= self.high_return_rate_percent <= 100:
            raise ValueError("high return-rate threshold must be between 0 and 100")
        if not 0 <= self.close_to_target_ratio <= 1:
            raise ValueError("close-to-target ratio must be between 0 and 1")
        if self.exceeded_target_ratio < 1:
            raise ValueError("exceeded-target ratio must be at least 1")


@dataclass(frozen=True, slots=True)
class ReportFormats:
    """Consistent workbook formats shared by every report worksheet."""

    theme: ReportTheme
    cover_title: Format
    cover_subtitle: Format
    title: Format
    subtitle: Format
    section_header: Format
    label: Format
    text: Format
    wrapped_text: Format
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
    neutral: Format
    note: Format
    hyperlink: Format
    navigation: Format
    card_title: Format
    card_currency: Format
    card_percentage: Format
    card_integer: Format
    card_positive: Format
    card_negative: Format
    card_neutral: Format


def create_report_formats(
    workbook: Workbook,
    currency_code: str = "USD",
    theme: ReportTheme = DEFAULT_THEME,
) -> ReportFormats:
    """Create all workbook formats from one visual theme."""
    base = {"font_name": theme.font_name, "font_color": theme.text}
    currency_pattern = f'#,##0.00 "{currency_code}";[Red]-#,##0.00 "{currency_code}"'
    return ReportFormats(
        theme=theme,
        cover_title=workbook.add_format(
            {
                **base,
                "bold": True,
                "font_size": 24,
                "font_color": theme.white,
                "bg_color": theme.primary,
                "align": "left",
                "valign": "vcenter",
            }
        ),
        cover_subtitle=workbook.add_format(
            {
                **base,
                "bold": True,
                "font_size": 15,
                "font_color": theme.primary,
                "align": "left",
                "valign": "vcenter",
            }
        ),
        title=workbook.add_format(
            {
                **base,
                "bold": True,
                "font_size": 20,
                "font_color": theme.primary,
                "bottom": 2,
                "bottom_color": theme.accent,
            }
        ),
        subtitle=workbook.add_format(
            {**base, "bold": True, "font_size": 12, "font_color": theme.accent}
        ),
        section_header=workbook.add_format(
            {
                **base,
                "bold": True,
                "font_color": theme.white,
                "bg_color": theme.primary,
                "align": "left",
                "valign": "vcenter",
            }
        ),
        label=workbook.add_format(
            {**base, "bold": True, "font_color": theme.primary, "align": "left"}
        ),
        text=workbook.add_format({**base, "valign": "top", "align": "left"}),
        wrapped_text=workbook.add_format(
            {**base, "valign": "top", "align": "left", "text_wrap": True}
        ),
        currency=workbook.add_format({**base, "num_format": currency_pattern, "align": "right"}),
        percentage=workbook.add_format({**base, "num_format": "0.0%", "align": "right"}),
        percentage_points=workbook.add_format({**base, "num_format": '0.0"%"', "align": "right"}),
        integer=workbook.add_format({**base, "num_format": "#,##0", "align": "right"}),
        decimal=workbook.add_format({**base, "num_format": "#,##0.00", "align": "right"}),
        date=workbook.add_format({**base, "num_format": "yyyy-mm-dd", "align": "right"}),
        datetime=workbook.add_format(
            {**base, "num_format": "yyyy-mm-dd hh:mm:ss", "align": "right"}
        ),
        warning=workbook.add_format(
            {**base, "bg_color": theme.warning_light, "font_color": "#9C5700"}
        ),
        error=workbook.add_format(
            {**base, "bg_color": theme.error_light, "font_color": theme.error}
        ),
        success=workbook.add_format(
            {**base, "bg_color": theme.positive_light, "font_color": "#375623"}
        ),
        neutral=workbook.add_format(
            {**base, "bg_color": theme.neutral_light, "font_color": "#595959"}
        ),
        note=workbook.add_format(
            {**base, "italic": True, "font_color": theme.neutral, "text_wrap": True}
        ),
        hyperlink=workbook.add_format(
            {**base, "font_color": theme.accent, "underline": True, "align": "left"}
        ),
        navigation=workbook.add_format(
            {
                **base,
                "bold": True,
                "font_color": theme.white,
                "bg_color": theme.accent,
                "align": "center",
                "valign": "vcenter",
            }
        ),
        card_title=workbook.add_format(
            {
                **base,
                "bold": True,
                "font_color": theme.white,
                "bg_color": theme.primary,
                "align": "center",
                "valign": "vcenter",
            }
        ),
        card_currency=workbook.add_format(
            {
                **base,
                "bold": True,
                "font_size": 16,
                "num_format": currency_pattern,
                "align": "center",
                "valign": "vcenter",
                "bg_color": theme.background,
            }
        ),
        card_percentage=workbook.add_format(
            {
                **base,
                "bold": True,
                "font_size": 16,
                "num_format": '0.0"%"',
                "align": "center",
                "valign": "vcenter",
                "bg_color": theme.background,
            }
        ),
        card_integer=workbook.add_format(
            {
                **base,
                "bold": True,
                "font_size": 16,
                "num_format": "#,##0",
                "align": "center",
                "valign": "vcenter",
                "bg_color": theme.background,
            }
        ),
        card_positive=workbook.add_format(
            {
                **base,
                "font_color": "#375623",
                "bg_color": theme.positive_light,
                "align": "center",
            }
        ),
        card_negative=workbook.add_format(
            {
                **base,
                "font_color": theme.error,
                "bg_color": theme.error_light,
                "align": "center",
            }
        ),
        card_neutral=workbook.add_format(
            {
                **base,
                "font_color": "#595959",
                "bg_color": theme.neutral_light,
                "align": "center",
            }
        ),
    )


def apply_worksheet_defaults(worksheet: Worksheet, formats: ReportFormats) -> None:
    """Apply consistent background, font-era spacing, and gridline choices."""
    worksheet.hide_gridlines(2)
    worksheet.set_default_row(formats.theme.body_row_height)
    worksheet.set_tab_color(formats.theme.primary)


def write_title(worksheet: Worksheet, title: str, formats: ReportFormats) -> None:
    """Write a standard detail-sheet title without merged data-table cells."""
    worksheet.write(0, 0, title, formats.title)
    worksheet.set_row(0, formats.theme.title_row_height)


def write_section_header(
    worksheet: Worksheet,
    row: int,
    title: str,
    formats: ReportFormats,
    *,
    width: int = 6,
) -> None:
    """Write a section heading across individually formatted cells."""
    worksheet.write(row, 0, title, formats.section_header)
    for column in range(1, width):
        worksheet.write_blank(row, column, None, formats.section_header)
    worksheet.set_row(row, formats.theme.section_row_height)


def write_internal_link(
    worksheet: Worksheet,
    cell: str,
    target_sheet: str,
    label: str,
    formats: ReportFormats,
    *,
    button: bool = False,
) -> None:
    """Write a workbook-internal navigation hyperlink."""
    worksheet.write_url(
        cell,
        f"internal:'{target_sheet}'!A1",
        formats.navigation if button else formats.hyperlink,
        label,
    )


def write_back_to_summary(worksheet: Worksheet, formats: ReportFormats) -> None:
    """Add the standard detail-sheet navigation link."""
    write_internal_link(
        worksheet,
        "A2",
        "01_Executive_Summary",
        "← Back to Summary",
        formats,
    )


def configure_print_layout(
    worksheet: Worksheet,
    *,
    report_id: str,
    generated_at: datetime,
    last_row: int,
    last_column: int,
    landscape: bool = True,
    repeat_header_row: int | None = None,
) -> None:
    """Configure predictable printing, margins, footer, and print area."""
    if landscape:
        worksheet.set_landscape()
    else:
        worksheet.set_portrait()
    worksheet.set_paper(9)
    worksheet.fit_to_pages(1, 0)
    worksheet.set_margins(left=0.35, right=0.35, top=0.55, bottom=0.55)
    if repeat_header_row is not None:
        worksheet.repeat_rows(repeat_header_row, repeat_header_row)
    worksheet.set_footer(
        f"&LReport ID: {report_id}&CGenerated {generated_at:%Y-%m-%d}&RPage &P of &N"
    )
    worksheet.print_area(0, 0, max(0, last_row), max(0, last_column))


def _column_format(column_name: str, formats: ReportFormats) -> Format:
    """Choose a display and alignment format from a canonical column name."""
    name = column_name.casefold()
    if name.endswith("_percent") or "margin_percent" in name:
        return formats.percentage_points
    if name in {"discount", "vat_rate", "target_achievement"}:
        return formats.percentage
    if "date" in name or name in {"day", "week"}:
        return formats.date
    if (
        any(
            token in name
            for token in ("revenue", "amount", "price", "cost", "profit", "refund", "target")
        )
        and name != "orders_target"
    ):
        return formats.currency
    if any(
        token in name for token in ("quantity", "orders", "units", "row_count", "rows", "count")
    ):
        return formats.integer
    if any(token in name for token in ("coverage", "average", "rate")):
        return formats.decimal
    if any(token in name for token in ("message", "explanation", "action", "reason", "metrics")):
        return formats.wrapped_text
    return formats.text


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
    normalized = _TABLE_NAME_PATTERN.sub("_", name)
    if not normalized or normalized[0].isdigit():
        normalized = f"Table_{normalized}"
    return normalized[:250]


def _supports_total(column_name: str) -> bool:
    name = column_name.casefold()
    return any(
        token in name
        for token in ("revenue", "amount", "profit", "cost", "quantity", "orders", "units")
    ) and not any(token in name for token in ("average", "margin", "rate", "price"))


def _logical_width(column: str, values: pd.Series) -> int:
    name = column.casefold()
    if any(token in name for token in ("message", "explanation", "action", "reason", "metrics")):
        return 38
    if "date" in name:
        return 14
    if any(token in name for token in ("id", "status", "category", "country", "channel")):
        return 18
    sample_lengths = [len(str(value)) for value in values.head(100)]
    return min(28, max([len(column) + 2, 12, *sample_lengths]))


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
    empty_message: str = "No data is available for the selected period.",
) -> int:
    """Write a usable formatted Excel table and return the next free row."""
    columns = [str(column) for column in dataframe.columns]
    if not columns:
        worksheet.write(start_row, start_column, empty_message, formats.note)
        return start_row + 3
    if dataframe.empty:
        worksheet.write_row(start_row, start_column, columns, formats.section_header)
        worksheet.write(start_row + 1, start_column, empty_message, formats.note)
        for offset, column in enumerate(columns):
            worksheet.set_column(
                start_column + offset, start_column + offset, max(12, len(column) + 2)
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
        definition: dict[str, object] = {
            "header": column,
            "format": _column_format(column, formats),
        }
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
        worksheet.set_column(
            start_column + offset,
            start_column + offset,
            _logical_width(column, dataframe.iloc[:, offset]),
            _column_format(column, formats),
        )
    if freeze_at is not None:
        worksheet.freeze_panes(*freeze_at)
    return last_table_row + 3


def write_key_values(
    worksheet: Worksheet,
    rows: list[tuple[str, object]],
    start_row: int,
    formats: ReportFormats,
) -> int:
    """Write labeled presentation values and return the next free row."""
    for offset, (label, value) in enumerate(rows):
        row = start_row + offset
        worksheet.write(row, 0, label, formats.label)
        converted = _excel_value(value)
        value_format: Format = formats.text
        if isinstance(value, datetime):
            value_format = formats.datetime
        elif isinstance(value, date):
            value_format = formats.date
        elif isinstance(value, int) and not isinstance(value, bool):
            value_format = formats.integer
        worksheet.write(row, 1, converted, value_format)
    worksheet.set_column(0, 0, 28)
    worksheet.set_column(1, 1, 34)
    return start_row + len(rows)
