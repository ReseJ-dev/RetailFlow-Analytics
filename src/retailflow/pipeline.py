"""End-to-end orchestration for RetailFlow source datasets."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

import pandas as pd

from retailflow.ingestion.column_mapper import ColumnMappingResult, map_columns
from retailflow.ingestion.models import LoadedDataset
from retailflow.models import (
    DatasetProcessingStatistics,
    ProcessingProgress,
    ProcessingResult,
    ProcessingStage,
    ProcessingStatistics,
)
from retailflow.transformation.cleaner import DataCleaner, DuplicateStrategy
from retailflow.transformation.merger import (
    merge_inventory_with_products,
    merge_orders_with_products,
    merge_orders_with_targets,
    merge_returns_with_orders_and_products,
)
from retailflow.transformation.normalizer import normalize_currency
from retailflow.validation import (
    DatasetType,
    DatasetValidationResult,
    DataValidator,
    ValidationIssue,
    ValidationSeverity,
    get_dataset_schema,
)

type ProgressCallback = Callable[[ProcessingProgress], None]
type ColumnOverrides = Mapping[DatasetType | str, Mapping[str, str]]

_LOGGER = logging.getLogger("retailflow")


@dataclass(slots=True)
class _DatasetState:
    dataset_type: DatasetType
    loaded: LoadedDataset
    mapped: pd.DataFrame
    mapping: ColumnMappingResult
    cleaned: pd.DataFrame
    excluded: pd.DataFrame
    issues: list[ValidationIssue]


def _normalized_type(value: DatasetType | str) -> DatasetType:
    return DatasetType.MONTHLY_TARGETS if value == "targets" else DatasetType(value)


def _structural_result(
    dataset_type: DatasetType,
    mapping: ColumnMappingResult,
    filename: str,
    row_count: int,
) -> DatasetValidationResult:
    issues: list[ValidationIssue] = []
    ambiguous_fields = set(mapping.ambiguous_matches)
    for field in mapping.missing_required_columns:
        if field in ambiguous_fields:
            continue
        issues.append(
            ValidationIssue(
                ValidationSeverity.ERROR,
                dataset_type,
                filename,
                None,
                field,
                "missing_required_column",
                f"Required column '{field}' is missing after column mapping.",
                None,
                f"Map or add the required '{field}' column.",
                False,
            )
        )
    for field, sources in mapping.ambiguous_matches.items():
        issues.append(
            ValidationIssue(
                ValidationSeverity.ERROR,
                dataset_type,
                filename,
                None,
                field,
                "ambiguous_column_mapping",
                f"Multiple source columns could map to '{field}'.",
                sources,
                "Provide an explicit column mapping override.",
                False,
            )
        )
    return DatasetValidationResult(dataset_type, filename, row_count, tuple(issues))


def _remap_issue_rows(
    issues: tuple[ValidationIssue, ...], frame: pd.DataFrame
) -> list[ValidationIssue]:
    remapped: list[ValidationIssue] = []
    for issue in issues:
        if issue.row_number is None:
            remapped.append(issue)
            continue
        position = issue.row_number - 2
        if position < 0 or position >= len(frame):
            remapped.append(issue)
            continue
        source_row = int(frame.iloc[position]["source_row_number"])
        remapped.append(replace(issue, row_number=source_row))
    return remapped


def _issue_reasons(issues: list[ValidationIssue], source_row: int) -> str:
    codes = sorted(
        {
            issue.issue_code
            for issue in issues
            if not issue.row_can_continue
            and (issue.row_number is None or issue.row_number == source_row)
        }
    )
    return "; ".join(codes) if codes else "excluded_by_processing_policy"


def _annotate_excluded(
    frame: pd.DataFrame, issues: list[ValidationIssue], dataset_type: DatasetType
) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        if "source_dataset" not in result:
            result["source_dataset"] = pd.Series(dtype="string")
        return result
    result["source_dataset"] = dataset_type.value
    result["processing_status"] = "excluded"
    result["exclusion_reason"] = [
        _issue_reasons(issues, int(row)) for row in result["source_row_number"]
    ]
    return result


def _exclude_blocked_rows(
    frame: pd.DataFrame,
    issues: list[ValidationIssue],
    dataset_type: DatasetType,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dataset_blocked = any(
        issue.row_number is None and not issue.row_can_continue for issue in issues
    )
    blocked_rows = {
        int(issue.row_number)
        for issue in issues
        if issue.row_number is not None and not issue.row_can_continue
    }
    mask = (
        pd.Series(True, index=frame.index)
        if dataset_blocked
        else frame["source_row_number"].isin(blocked_rows)
    )
    excluded = _annotate_excluded(frame.loc[mask].copy(), issues, dataset_type)
    kept = frame.loc[~mask].copy().reset_index(drop=True)
    kept["processing_status"] = "processed"
    kept["exclusion_reason"] = pd.NA
    return kept, excluded.reset_index(drop=True)


class DataProcessingPipeline:
    """Map, validate, clean, merge, and summarize all supplied datasets."""

    def __init__(
        self,
        *,
        default_currency: str | None = None,
        exchange_rates: Mapping[str, float] | None = None,
        duplicate_strategy: DuplicateStrategy | str = DuplicateStrategy.KEEP_FIRST,
        month_first: bool = False,
    ) -> None:
        self.default_currency = default_currency
        self.exchange_rates = exchange_rates
        self.duplicate_strategy = duplicate_strategy
        self.month_first = month_first

    @staticmethod
    def _notify(
        callback: ProgressCallback | None,
        stage: ProcessingStage,
        step: int,
        message: str,
    ) -> None:
        if callback is not None:
            callback(ProcessingProgress(stage, step, 5, message))

    @staticmethod
    def _map_source(
        dataset_type: DatasetType,
        loaded: LoadedDataset,
        overrides: Mapping[str, str] | None,
    ) -> tuple[pd.DataFrame, ColumnMappingResult]:
        mapping = map_columns(
            tuple(str(column) for column in loaded.dataframe.columns),
            dataset_type,
            manual_overrides=overrides,
        )
        frame = loaded.dataframe.rename(columns=mapping.column_mapping).copy(deep=True)
        for column in get_dataset_schema(dataset_type).required_columns:
            if column not in frame:
                frame[column] = pd.NA
        frame["source_file"] = loaded.filename
        frame["source_row_number"] = range(2, len(frame) + 2)
        frame["processing_status"] = "pending"
        frame["exclusion_reason"] = pd.NA
        return frame, mapping

    def _resolve_default_currency(self, orders: pd.DataFrame) -> str:
        if self.default_currency is not None:
            return self.default_currency
        if "currency" in orders:
            currencies = [
                value
                for raw in orders["currency"]
                if isinstance((value := normalize_currency(raw)), str)
            ]
            if currencies:
                return Counter(currencies).most_common(1)[0][0]
        return "USD"

    def process(
        self,
        orders: LoadedDataset,
        products: LoadedDataset,
        inventory: LoadedDataset,
        returns: LoadedDataset,
        targets: LoadedDataset | None = None,
        *,
        column_overrides: ColumnOverrides | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> ProcessingResult:
        """Process required loaded datasets and an optional monthly targets file."""
        loaded_inputs: dict[DatasetType, LoadedDataset] = {
            DatasetType.ORDERS: orders,
            DatasetType.PRODUCTS: products,
            DatasetType.INVENTORY: inventory,
            DatasetType.RETURNS: returns,
        }
        if targets is not None:
            loaded_inputs[DatasetType.MONTHLY_TARGETS] = targets
        normalized_overrides = {
            _normalized_type(key): value for key, value in (column_overrides or {}).items()
        }

        states: dict[DatasetType, _DatasetState] = {}
        for dataset_type, loaded in loaded_inputs.items():
            mapped, mapping = self._map_source(
                dataset_type, loaded, normalized_overrides.get(dataset_type)
            )
            states[dataset_type] = _DatasetState(
                dataset_type, loaded, mapped, mapping, pd.DataFrame(), pd.DataFrame(), []
            )
        self._notify(progress_callback, ProcessingStage.MAPPING, 1, "Columns mapped")
        _LOGGER.info("Mapped %d source datasets", len(states))

        cleaner = DataCleaner(
            default_currency=self._resolve_default_currency(states[DatasetType.ORDERS].mapped),
            exchange_rates=self.exchange_rates,
            duplicate_strategy=self.duplicate_strategy,
            month_first=self.month_first,
        )
        for state in states.values():
            structural = _structural_result(
                state.dataset_type,
                state.mapping,
                state.loaded.filename,
                len(state.mapped),
            )
            result = cleaner.clean(
                state.dataset_type,
                state.mapped,
                validation_result=structural,
                source_filename=state.loaded.filename,
            )
            state.cleaned = result.cleaned_dataframe
            state.issues = list(result.issues)
            state.excluded = _annotate_excluded(
                result.excluded_rows, state.issues, state.dataset_type
            )
        self._notify(
            progress_callback,
            ProcessingStage.TRANSFORMATION,
            2,
            "Values normalized and cleaned",
        )
        _LOGGER.info(
            "Transformation completed for %d input rows",
            sum(len(state.mapped) for state in states.values()),
        )

        validator = DataValidator(cleaner.currency_converter.supported_currencies)
        self._apply_business_validation(states, validator)
        self._notify(
            progress_callback,
            ProcessingStage.VALIDATION,
            3,
            "Business rules validated",
        )

        products_frame = states[DatasetType.PRODUCTS].cleaned
        orders_frame = merge_orders_with_products(
            states[DatasetType.ORDERS].cleaned, products_frame
        )
        targets_frame = (
            states[DatasetType.MONTHLY_TARGETS].cleaned
            if DatasetType.MONTHLY_TARGETS in states
            else pd.DataFrame()
        )
        orders_frame = merge_orders_with_targets(orders_frame, targets_frame)
        inventory_frame = merge_inventory_with_products(
            states[DatasetType.INVENTORY].cleaned, products_frame
        )
        returns_frame = merge_returns_with_orders_and_products(
            states[DatasetType.RETURNS].cleaned,
            states[DatasetType.ORDERS].cleaned,
            products_frame,
        )
        self._notify(progress_callback, ProcessingStage.MERGING, 4, "Datasets safely merged")
        _LOGGER.info(
            "Merged %d orders, %d inventory rows, and %d returns",
            len(orders_frame),
            len(inventory_frame),
            len(returns_frame),
        )

        excluded = pd.concat(
            [state.excluded for state in states.values()], ignore_index=True, sort=False
        )
        issues = tuple(issue for state in states.values() for issue in state.issues)
        statistics = ProcessingStatistics(
            {
                dataset_type: DatasetProcessingStatistics(
                    input_rows=len(state.mapped),
                    processed_rows=len(state.cleaned),
                    excluded_rows=len(state.excluded),
                    issue_count=len(state.issues),
                )
                for dataset_type, state in states.items()
            }
        )
        self._notify(progress_callback, ProcessingStage.COMPLETE, 5, "Processing complete")
        _LOGGER.info(
            "Processing completed: %d input rows, %d excluded rows, %d issues",
            statistics.total_input_rows,
            statistics.total_excluded_rows,
            statistics.total_issues,
        )
        return ProcessingResult(
            processed_orders=orders_frame,
            products=products_frame,
            inventory=inventory_frame,
            returns=returns_frame,
            targets=targets_frame,
            excluded_rows=excluded,
            validation_issues=issues,
            statistics=statistics,
            source_metadata={
                dataset_type: state.loaded.metadata for dataset_type, state in states.items()
            },
        )

    @staticmethod
    def _apply_business_validation(
        states: dict[DatasetType, _DatasetState], validator: DataValidator
    ) -> None:
        products_state = states[DatasetType.PRODUCTS]
        DataProcessingPipeline._validate_state(
            products_state,
            validator.validate_products(
                products_state.cleaned,
                source_filename=products_state.loaded.filename,
            ),
        )

        orders_state = states[DatasetType.ORDERS]
        order_validation = validator.validate_orders(
            orders_state.cleaned, source_filename=orders_state.loaded.filename
        )
        order_issues = _remap_issue_rows(order_validation.issues, orders_state.cleaned)
        known_products = frozenset(products_state.cleaned["product_id"].astype(str))
        for _, row in orders_state.cleaned.iterrows():
            if str(row["product_id"]) not in known_products:
                order_issues.append(
                    ValidationIssue(
                        ValidationSeverity.ERROR,
                        DatasetType.ORDERS,
                        orders_state.loaded.filename,
                        int(row["source_row_number"]),
                        "product_id",
                        "unknown_product_id",
                        "Order references an unknown product ID.",
                        row["product_id"],
                        "Correct the product ID or add the referenced product.",
                        False,
                    )
                )
        DataProcessingPipeline._filter_state(orders_state, order_issues)

        inventory_state = states[DatasetType.INVENTORY]
        DataProcessingPipeline._validate_state(
            inventory_state,
            validator.validate_inventory(
                inventory_state.cleaned,
                products=products_state.cleaned,
                source_filename=inventory_state.loaded.filename,
            ),
        )

        returns_state = states[DatasetType.RETURNS]
        DataProcessingPipeline._validate_state(
            returns_state,
            validator.validate_returns(
                returns_state.cleaned,
                orders=orders_state.cleaned,
                products=products_state.cleaned,
                source_filename=returns_state.loaded.filename,
            ),
        )

        targets_state = states.get(DatasetType.MONTHLY_TARGETS)
        if targets_state is not None:
            DataProcessingPipeline._validate_state(
                targets_state,
                validator.validate_targets(
                    targets_state.cleaned,
                    source_filename=targets_state.loaded.filename,
                ),
            )

    @staticmethod
    def _validate_state(state: _DatasetState, validation: DatasetValidationResult) -> None:
        DataProcessingPipeline._filter_state(
            state, _remap_issue_rows(validation.issues, state.cleaned)
        )

    @staticmethod
    def _filter_state(state: _DatasetState, business_issues: list[ValidationIssue]) -> None:
        state.issues.extend(business_issues)
        kept, excluded = _exclude_blocked_rows(state.cleaned, business_issues, state.dataset_type)
        state.cleaned = kept
        if not excluded.empty:
            state.excluded = pd.concat([state.excluded, excluded], ignore_index=True, sort=False)


def process_datasets(
    orders: LoadedDataset,
    products: LoadedDataset,
    inventory: LoadedDataset,
    returns: LoadedDataset,
    targets: LoadedDataset | None = None,
    *,
    progress_callback: ProgressCallback | None = None,
) -> ProcessingResult:
    """Convenience function using inferred source currency and default policies."""
    return DataProcessingPipeline().process(
        orders,
        products,
        inventory,
        returns,
        targets,
        progress_callback=progress_callback,
    )


__all__ = [
    "ColumnOverrides",
    "DataProcessingPipeline",
    "ProgressCallback",
    "process_datasets",
]
