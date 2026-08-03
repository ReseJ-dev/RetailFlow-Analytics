"""Dataset cleaning orchestration and transformation result models."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

import pandas as pd

from retailflow.ingestion.models import LoadedDataset
from retailflow.transformation.currency_converter import CurrencyConverter
from retailflow.transformation.normalizer import (
    is_missing,
    normalize_country,
    normalize_currency,
    normalize_identifier,
    normalize_order_status,
    normalize_sales_channel,
    normalize_string,
    parse_date,
    parse_integer,
    parse_number,
)
from retailflow.validation.schemas import DatasetType
from retailflow.validation.validation_result import (
    DatasetValidationResult,
    ValidationIssue,
    ValidationSeverity,
)

type DatasetInput = pd.DataFrame | LoadedDataset


class DuplicateStrategy(StrEnum):
    KEEP_FIRST = "keep_first"
    KEEP_LATEST = "keep_latest"
    EXCLUDE_ALL = "exclude_all"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TransformationStatistics:
    input_rows: int
    cleaned_rows: int
    excluded_rows: int
    changed_values: int
    invalid_values: int
    duplicate_rows: int
    changes_by_field: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransformationResult:
    cleaned_dataframe: pd.DataFrame
    excluded_rows: pd.DataFrame
    transformation_issues: tuple[ValidationIssue, ...]
    statistics: TransformationStatistics

    @property
    def dataframe(self) -> pd.DataFrame:
        return self.cleaned_dataframe

    @property
    def issues(self) -> tuple[ValidationIssue, ...]:
        return self.transformation_issues


IDENTIFIER_FIELDS = frozenset({"order_id", "product_id", "customer_id", "return_id"})
STRING_FIELDS = frozenset(
    {
        "product_name",
        "category",
        "supplier",
        "warehouse",
        "return_reason",
    }
)
INTEGER_FIELDS: dict[DatasetType, frozenset[str]] = {
    DatasetType.ORDERS: frozenset({"quantity"}),
    DatasetType.INVENTORY: frozenset({"stock_quantity", "reserved_quantity", "reorder_level"}),
    DatasetType.RETURNS: frozenset({"quantity"}),
    DatasetType.MONTHLY_TARGETS: frozenset({"orders_target"}),
    DatasetType.PRODUCTS: frozenset(),
}
NUMBER_FIELDS: dict[DatasetType, frozenset[str]] = {
    DatasetType.ORDERS: frozenset({"unit_price"}),
    DatasetType.PRODUCTS: frozenset({"purchase_cost", "recommended_price"}),
    DatasetType.INVENTORY: frozenset(),
    DatasetType.RETURNS: frozenset({"refund_amount"}),
    DatasetType.MONTHLY_TARGETS: frozenset({"revenue_target", "profit_target"}),
}
PERCENT_FIELDS: dict[DatasetType, frozenset[str]] = {
    DatasetType.ORDERS: frozenset({"discount"}),
    DatasetType.PRODUCTS: frozenset({"vat_rate"}),
    DatasetType.INVENTORY: frozenset(),
    DatasetType.RETURNS: frozenset(),
    DatasetType.MONTHLY_TARGETS: frozenset(),
}
DATE_FIELDS: dict[DatasetType, frozenset[str]] = {
    DatasetType.ORDERS: frozenset({"order_date"}),
    DatasetType.PRODUCTS: frozenset(),
    DatasetType.INVENTORY: frozenset({"last_restock_date"}),
    DatasetType.RETURNS: frozenset({"return_date"}),
    DatasetType.MONTHLY_TARGETS: frozenset(),
}
DUPLICATE_KEYS: dict[DatasetType, tuple[str, ...]] = {
    DatasetType.ORDERS: ("order_id", "product_id"),
    DatasetType.PRODUCTS: ("product_id",),
    DatasetType.INVENTORY: ("product_id", "warehouse"),
    DatasetType.RETURNS: ("return_id",),
    DatasetType.MONTHLY_TARGETS: ("month",),
}
LATEST_FIELDS: dict[DatasetType, str | None] = {
    DatasetType.ORDERS: "order_date",
    DatasetType.PRODUCTS: None,
    DatasetType.INVENTORY: "last_restock_date",
    DatasetType.RETURNS: "return_date",
    DatasetType.MONTHLY_TARGETS: "month",
}


def _dataset_type(value: DatasetType | str) -> DatasetType:
    return DatasetType.MONTHLY_TARGETS if value == "targets" else DatasetType(value)


def _strategy(value: DuplicateStrategy | str) -> DuplicateStrategy:
    aliases = {"keep_last": "keep_latest", "remove_all": "exclude_all"}
    return DuplicateStrategy(aliases.get(str(value), str(value)))


def _changed(before: object, after: object) -> bool:
    if is_missing(before) and is_missing(after):
        return False
    if is_missing(before) != is_missing(after):
        return True
    return bool(before != after)


class DataCleaner:
    """Normalize one canonical dataset and retain rejected source rows."""

    def __init__(
        self,
        *,
        default_currency: str = "USD",
        exchange_rates: Mapping[str, float] | None = None,
        duplicate_strategy: DuplicateStrategy | str = DuplicateStrategy.KEEP_FIRST,
        month_first: bool = False,
    ) -> None:
        self.currency_converter = CurrencyConverter(default_currency, exchange_rates)
        self.duplicate_strategy = _strategy(duplicate_strategy)
        self.month_first = month_first

    def clean(
        self,
        dataset_type: DatasetType | str,
        data: DatasetInput,
        *,
        validation_result: DatasetValidationResult | None = None,
        source_filename: str | None = None,
        duplicate_strategy: DuplicateStrategy | str | None = None,
    ) -> TransformationResult:
        normalized_type = _dataset_type(dataset_type)
        filename: str | None
        if isinstance(data, LoadedDataset):
            frame = data.dataframe.copy(deep=True)
            filename = source_filename or data.filename
        elif isinstance(data, pd.DataFrame):
            frame = data.copy(deep=True)
            filename = source_filename
        else:
            raise TypeError("Cleaning expects a pandas DataFrame or LoadedDataset.")

        source = frame.copy(deep=True)
        frame["__source_row"] = range(2, len(frame) + 2)
        issues = list(validation_result.issues if validation_result else ())
        changes: Counter[str] = Counter()
        invalid_values = 0

        for column in frame.columns:
            if column == "__source_row":
                continue
            if column in IDENTIFIER_FIELDS:
                invalid_values += self._apply(frame, column, normalize_identifier, changes)
            elif column in STRING_FIELDS:
                invalid_values += self._apply(frame, column, normalize_string, changes)
        if "country" in frame:
            invalid_values += self._apply(frame, "country", normalize_country, changes)
        if "order_status" in frame:
            invalid_values += self._apply(frame, "order_status", normalize_order_status, changes)
        if "sales_channel" in frame:
            invalid_values += self._apply(frame, "sales_channel", normalize_sales_channel, changes)

        for column in INTEGER_FIELDS[normalized_type]:
            invalid_values += self._convert_column(
                frame, column, parse_integer, normalized_type, filename, issues, changes
            )
        for column in NUMBER_FIELDS[normalized_type]:
            invalid_values += self._convert_column(
                frame, column, parse_number, normalized_type, filename, issues, changes
            )
        for column in PERCENT_FIELDS[normalized_type]:
            invalid_values += self._convert_column(
                frame,
                column,
                lambda value: parse_number(value, percentage=False),
                normalized_type,
                filename,
                issues,
                changes,
                percentage=True,
            )
        for column in DATE_FIELDS[normalized_type]:
            invalid_values += self._convert_column(
                frame,
                column,
                lambda value: parse_date(value, month_first=self.month_first),
                normalized_type,
                filename,
                issues,
                changes,
                date_value=True,
            )
        if normalized_type is DatasetType.MONTHLY_TARGETS and "month" in frame:
            invalid_values += self._convert_month(frame, filename, issues, changes)
        if normalized_type in {DatasetType.ORDERS, DatasetType.RETURNS}:
            invalid_values += self._convert_currency(
                normalized_type, frame, filename, issues, changes
            )

        excluded_row_numbers = self._blocking_rows(issues, frame)
        candidate = frame.loc[~frame["__source_row"].isin(excluded_row_numbers)].copy()
        duplicate_excluded, duplicate_issues = self._handle_duplicates(
            normalized_type,
            candidate,
            filename,
            _strategy(duplicate_strategy or self.duplicate_strategy),
        )
        issues.extend(duplicate_issues)
        excluded_row_numbers.update(duplicate_excluded)

        clean = frame.loc[~frame["__source_row"].isin(excluded_row_numbers)].copy()
        excluded_positions = [row - 2 for row in sorted(excluded_row_numbers)]
        excluded = (
            source.iloc[excluded_positions].copy()
            if excluded_positions
            else source.iloc[0:0].copy()
        )
        clean = clean.drop(columns="__source_row").reset_index(drop=True)
        excluded = excluded.reset_index(drop=True)
        stats = TransformationStatistics(
            input_rows=len(source),
            cleaned_rows=len(clean),
            excluded_rows=len(excluded),
            changed_values=sum(changes.values()),
            invalid_values=invalid_values,
            duplicate_rows=len(duplicate_excluded),
            changes_by_field=dict(changes),
        )
        return TransformationResult(clean, excluded, tuple(issues), stats)

    def clean_orders(
        self,
        data: DatasetInput,
        *,
        validation_result: DatasetValidationResult | None = None,
        source_filename: str | None = None,
        duplicate_strategy: DuplicateStrategy | str | None = None,
    ) -> TransformationResult:
        """Clean an orders dataset."""
        return self.clean(
            DatasetType.ORDERS,
            data,
            validation_result=validation_result,
            source_filename=source_filename,
            duplicate_strategy=duplicate_strategy,
        )

    def clean_products(self, data: DatasetInput) -> TransformationResult:
        """Clean a products dataset."""
        return self.clean(DatasetType.PRODUCTS, data)

    def clean_inventory(self, data: DatasetInput) -> TransformationResult:
        """Clean an inventory dataset."""
        return self.clean(DatasetType.INVENTORY, data)

    def clean_returns(self, data: DatasetInput) -> TransformationResult:
        """Clean a returns dataset."""
        return self.clean(DatasetType.RETURNS, data)

    def clean_targets(self, data: DatasetInput) -> TransformationResult:
        """Clean a monthly targets dataset."""
        return self.clean(DatasetType.MONTHLY_TARGETS, data)

    @staticmethod
    def _apply(
        frame: pd.DataFrame,
        column: str,
        converter: Callable[[object], object],
        changes: Counter[str],
    ) -> int:
        if column not in frame:
            return 0
        converted = []
        for value in frame[column]:
            result = converter(value)
            changes[column] += int(_changed(value, result))
            converted.append(result)
        frame[column] = converted  # type: ignore[assignment]
        return 0

    def _convert_column(
        self,
        frame: pd.DataFrame,
        column: str,
        converter: Callable[[object], object],
        dataset_type: DatasetType,
        filename: str | None,
        issues: list[ValidationIssue],
        changes: Counter[str],
        *,
        percentage: bool = False,
        date_value: bool = False,
    ) -> int:
        if column not in frame:
            return 0
        invalid = 0
        converted: list[object] = []
        for value, row_number in zip(frame[column], frame["__source_row"], strict=True):
            result = converter(value)
            if result is None and not is_missing(value):
                invalid += 1
                issues.append(
                    ValidationIssue(
                        ValidationSeverity.ERROR,
                        dataset_type,
                        filename,
                        int(row_number),
                        column,
                        "invalid_date" if date_value else "invalid_numeric_value",
                        f"'{column}' could not be converted.",
                        value,
                        "Correct the source value or leave it empty.",
                        False,
                    )
                )
            final = pd.NA if result is None else result
            changes[column] += int(_changed(value, final))
            converted.append(final)
        if date_value:
            frame[column] = pd.to_datetime(  # type: ignore[call-overload]
                converted, errors="coerce"
            )
        elif percentage:
            frame[column] = pd.array(converted, dtype="Float64")  # type: ignore[call-overload]
        elif column in INTEGER_FIELDS[dataset_type]:
            frame[column] = pd.array(converted, dtype="Int64")  # type: ignore[call-overload]
        else:
            frame[column] = pd.array(converted, dtype="Float64")  # type: ignore[call-overload]
        return invalid

    def _convert_month(
        self,
        frame: pd.DataFrame,
        filename: str | None,
        issues: list[ValidationIssue],
        changes: Counter[str],
    ) -> int:
        invalid = 0
        converted: list[object] = []
        for value, row_number in zip(frame["month"], frame["__source_row"], strict=True):
            parsed = (
                parse_date(f"{value}-01", month_first=False)
                if isinstance(value, str) and len(value.strip()) == 7
                else parse_date(value, month_first=self.month_first)
            )
            if parsed is None and not is_missing(value):
                invalid += 1
                issues.append(
                    ValidationIssue(
                        ValidationSeverity.ERROR,
                        DatasetType.MONTHLY_TARGETS,
                        filename,
                        int(row_number),
                        "month",
                        "invalid_month",
                        "Month could not be converted.",
                        value,
                        "Use YYYY-MM or a valid date.",
                        False,
                    )
                )
            final = pd.NA if parsed is None else parsed.strftime("%Y-%m")
            changes["month"] += int(_changed(value, final))
            converted.append(final)
        frame["month"] = converted  # type: ignore[assignment]
        return invalid

    def _convert_currency(
        self,
        dataset_type: DatasetType,
        frame: pd.DataFrame,
        filename: str | None,
        issues: list[ValidationIssue],
        changes: Counter[str],
    ) -> int:
        if "currency" not in frame:
            return 0
        amount_field = "unit_price" if dataset_type is DatasetType.ORDERS else "refund_amount"
        invalid = 0
        for index, row in frame.iterrows():
            original = row["currency"]
            currency = normalize_currency(original)
            if is_missing(currency):
                currency = self.currency_converter.default_currency
            currency = str(currency)
            if not self.currency_converter.supports(currency):
                invalid += 1
                issues.append(
                    ValidationIssue(
                        ValidationSeverity.ERROR,
                        dataset_type,
                        filename,
                        int(row["__source_row"]),
                        "currency",
                        "unsupported_currency",
                        f"Currency '{currency}' has no configured exchange rate.",
                        original,
                        "Add an exchange rate or use a supported currency.",
                        False,
                    )
                )
                frame.at[index, "currency"] = currency
                continue
            amount = row.get(amount_field)
            if not is_missing(amount):
                converted = self.currency_converter.convert(float(str(amount)), currency)
                changes[amount_field] += int(_changed(amount, converted))
                frame.at[index, amount_field] = converted
            changes["currency"] += int(_changed(original, self.currency_converter.default_currency))
            frame.at[index, "currency"] = self.currency_converter.default_currency
        return invalid

    @staticmethod
    def _blocking_rows(issues: list[ValidationIssue], frame: pd.DataFrame) -> set[int]:
        if any(issue.row_number is None and not issue.row_can_continue for issue in issues):
            return set(int(value) for value in frame["__source_row"])
        return {
            int(issue.row_number)
            for issue in issues
            if issue.row_number is not None and not issue.row_can_continue
        }

    @staticmethod
    def _handle_duplicates(
        dataset_type: DatasetType,
        frame: pd.DataFrame,
        filename: str | None,
        strategy: DuplicateStrategy,
    ) -> tuple[set[int], list[ValidationIssue]]:
        keys = [key for key in DUPLICATE_KEYS[dataset_type] if key in frame]
        if len(keys) != len(DUPLICATE_KEYS[dataset_type]):
            return set(), []
        all_duplicates = frame.duplicated(keys, keep=False)
        if not all_duplicates.any():
            return set(), []
        if strategy is DuplicateStrategy.KEEP_FIRST:
            excluded_mask = frame.duplicated(keys, keep="first")
        elif strategy is DuplicateStrategy.KEEP_LATEST:
            latest = LATEST_FIELDS[dataset_type]
            if latest and latest in frame:
                winners = frame.loc[all_duplicates].groupby(keys, dropna=False)[latest].idxmax()
                excluded_mask = all_duplicates & ~frame.index.isin(winners)
            else:
                excluded_mask = frame.duplicated(keys, keep="last")
        else:
            excluded_mask = all_duplicates
        excluded = set(int(value) for value in frame.loc[excluded_mask, "__source_row"])
        severity = (
            ValidationSeverity.ERROR
            if strategy is DuplicateStrategy.ERROR
            else ValidationSeverity.WARNING
        )
        issues = [
            ValidationIssue(
                severity,
                dataset_type,
                filename,
                row,
                ", ".join(keys),
                "duplicate_row",
                f"Duplicate row excluded using '{strategy.value}'.",
                tuple(frame.loc[frame["__source_row"] == row, keys].iloc[0]),
                "Review duplicate source records.",
                False,
            )
            for row in sorted(excluded)
        ]
        return excluded, issues


def clean_dataset(
    dataset_type: DatasetType | str,
    data: DatasetInput,
    *,
    validation_result: DatasetValidationResult | None = None,
    source_filename: str | None = None,
    duplicate_strategy: DuplicateStrategy | str | None = None,
) -> TransformationResult:
    """Convenience entry point using default cleaner settings."""
    return DataCleaner().clean(
        dataset_type,
        data,
        validation_result=validation_result,
        source_filename=source_filename,
        duplicate_strategy=duplicate_strategy,
    )
