"""Pure value normalizers used by the transformation pipeline."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd

COUNTRY_ALIASES = {
    "cy": "Cyprus",
    "cyprus": "Cyprus",
    "de": "Germany",
    "deutschland": "Germany",
    "germany": "Germany",
    "es": "Spain",
    "españa": "Spain",
    "spain": "Spain",
    "fr": "France",
    "france": "France",
    "gr": "Greece",
    "greece": "Greece",
    "hellas": "Greece",
    "it": "Italy",
    "italia": "Italy",
    "italy": "Italy",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "great britain": "United Kingdom",
    "united kingdom": "United Kingdom",
    "us": "United States",
    "u.s.": "United States",
    "usa": "United States",
    "united states of america": "United States",
    "united states": "United States",
}
STATUS_ALIASES = {
    "complete": "completed",
    "completed": "completed",
    "paid": "completed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "pending": "pending",
    "in progress": "pending",
    "processing": "pending",
    "refunded": "refunded",
    "returned": "returned",
}
CHANNEL_ALIASES = {
    "web": "website",
    "online": "website",
    "ecommerce": "website",
    "e-commerce": "website",
    "website": "website",
    "amazon": "amazon",
    "marketplace": "marketplace",
    "retail": "retail",
    "store": "retail",
    "wholesale": "wholesale",
}
ISO_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}(?:$|[T ])")
SLASH_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


def is_missing(value: object) -> bool:
    """Return whether a scalar should be treated as missing."""
    if value is None:
        return True
    try:
        return bool(pd.isna(value))  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return False


def normalize_string(value: object) -> object:
    """Trim a value and turn blank strings into pandas' missing sentinel."""
    if is_missing(value):
        return pd.NA
    normalized = str(value).strip()
    return normalized if normalized else pd.NA


def normalize_identifier(value: object) -> object:
    """Normalize surrounding/internal whitespace while preserving hyphens."""
    normalized = normalize_string(value)
    if is_missing(normalized):
        return pd.NA
    return " ".join(str(normalized).split())


def normalize_country(value: object) -> object:
    normalized = normalize_string(value)
    if is_missing(normalized):
        return pd.NA
    text = " ".join(str(normalized).split())
    return COUNTRY_ALIASES.get(text.casefold(), text.title())


def normalize_currency(value: object) -> object:
    normalized = normalize_string(value)
    return pd.NA if is_missing(normalized) else str(normalized).upper()


def normalize_order_status(value: object) -> object:
    normalized = normalize_string(value)
    if is_missing(normalized):
        return pd.NA
    text = " ".join(str(normalized).casefold().replace("_", "-").split())
    return STATUS_ALIASES.get(text.replace("-", " "), text)


def normalize_sales_channel(value: object) -> object:
    normalized = normalize_string(value)
    if is_missing(normalized):
        return pd.NA
    text = " ".join(str(normalized).casefold().replace("_", " ").split())
    return CHANNEL_ALIASES.get(text, text)


def parse_number(value: object, *, percentage: bool = False) -> float | None:
    """Parse localized numeric text; percentages are returned as fractions."""
    if is_missing(value) or isinstance(value, bool):
        return None
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    has_percent = text.endswith("%")
    if has_percent:
        text = text[:-1]
    text = "".join(char for char in text if char not in "$€£¥")
    if "," in text and "." in text:
        decimal_separator = "," if text.rfind(",") > text.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        text = text.replace(thousands_separator, "").replace(decimal_separator, ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        number = float(Decimal(text))
    except (InvalidOperation, ValueError):
        return None
    return number / 100 if has_percent or percentage else number


def parse_integer(value: object) -> int | None:
    number = parse_number(value)
    if number is None or not float(number).is_integer():
        return None
    return int(number)


def parse_date(value: object, *, month_first: bool = False) -> pd.Timestamp | None:
    """Parse dates, including Excel serials using Excel's 1900 date system."""
    if is_missing(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        parsed = pd.Timestamp(value)
        return None if pd.isna(parsed) else parsed.normalize()
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        try:
            parsed = pd.to_datetime(float(value), unit="D", origin="1899-12-30")
        except (ValueError, TypeError, OverflowError):
            return None
        return pd.Timestamp(parsed).normalize()
    text = str(value).strip()
    if not text:
        return None
    try:
        if ISO_DATE_PREFIX.match(text):
            parsed = pd.Timestamp(text)
        elif SLASH_DATE.match(text):
            date_format = "%m/%d/%Y" if month_first else "%d/%m/%Y"
            parsed = pd.Timestamp(datetime.strptime(text, date_format))
        else:
            parsed = pd.to_datetime(text, dayfirst=not month_first, errors="raise")
    except (ValueError, TypeError, OverflowError):
        return None
    return pd.Timestamp(parsed).normalize()
