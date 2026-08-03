"""High-level validation orchestration for loaded RetailFlow datasets."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from retailflow.ingestion.models import LoadedDataset
from retailflow.validation import business_rules
from retailflow.validation.schemas import DatasetType, get_dataset_schema
from retailflow.validation.validation_result import (
    CombinedValidationResult,
    DatasetValidationResult,
    ValidationIssue,
    ValidationSeverity,
    issues_to_dataframe,
)

type DatasetInput = pd.DataFrame | LoadedDataset


def _dataset_type(value: DatasetType | str) -> DatasetType:
    return DatasetType.MONTHLY_TARGETS if value == "targets" else DatasetType(value)


def _unpack(data: DatasetInput, source_filename: str | None) -> tuple[pd.DataFrame, str | None]:
    if isinstance(data, LoadedDataset):
        return data.dataframe, source_filename or data.filename
    if not isinstance(data, pd.DataFrame):
        raise TypeError("Validation expects a pandas DataFrame or LoadedDataset.")
    return data, source_filename


def _known_product_ids(products: pd.DataFrame | None) -> frozenset[str] | None:
    if products is None or "product_id" not in products:
        return None
    return frozenset(
        str(value).strip()
        for value in products["product_id"]
        if not business_rules.is_missing(value)
    )


class DataValidator:
    """Validate canonical datasets and their cross-dataset relationships."""

    def __init__(self, supported_currencies: set[str] | frozenset[str] | None = None) -> None:
        currencies = supported_currencies or business_rules.DEFAULT_SUPPORTED_CURRENCIES
        self.supported_currencies = frozenset(currency.strip().upper() for currency in currencies)

    def _required_column_issues(
        self,
        dataset_type: DatasetType,
        frame: pd.DataFrame,
        filename: str | None,
    ) -> list[ValidationIssue]:
        schema = get_dataset_schema(dataset_type)
        return [
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                source_dataset=dataset_type,
                source_filename=filename,
                row_number=None,
                field=column,
                issue_code="missing_required_column",
                message=f"Required column '{column}' is missing.",
                original_value=None,
                recommended_action=f"Map or add the required '{column}' column.",
                row_can_continue=False,
            )
            for column in schema.required_columns
            if column not in frame.columns
        ]

    def validate_dataset(
        self,
        dataset_type: DatasetType | str,
        data: DatasetInput,
        *,
        source_filename: str | None = None,
        products: DatasetInput | None = None,
        orders: DatasetInput | None = None,
    ) -> DatasetValidationResult:
        """Validate one dataset with optional product and order references."""
        normalized_type = _dataset_type(dataset_type)
        frame, filename = _unpack(data, source_filename)
        product_frame = _unpack(products, None)[0] if products is not None else None
        order_frame = _unpack(orders, None)[0] if orders is not None else None
        issues = self._required_column_issues(normalized_type, frame, filename)

        if normalized_type is DatasetType.ORDERS:
            issues.extend(
                business_rules.validate_orders(
                    frame,
                    filename,
                    supported_currencies=self.supported_currencies,
                )
            )
        elif normalized_type is DatasetType.PRODUCTS:
            issues.extend(business_rules.validate_products(frame, filename))
        elif normalized_type is DatasetType.INVENTORY:
            issues.extend(
                business_rules.validate_inventory(
                    frame,
                    filename,
                    known_product_ids=_known_product_ids(product_frame),
                )
            )
        elif normalized_type is DatasetType.RETURNS:
            known_order_ids, references = business_rules.build_order_references(order_frame)
            issues.extend(
                business_rules.validate_returns(
                    frame,
                    filename,
                    known_product_ids=_known_product_ids(product_frame),
                    known_order_ids=known_order_ids,
                    order_references=references,
                )
            )
        else:
            issues.extend(business_rules.validate_targets(frame, filename))

        return DatasetValidationResult(
            dataset_type=normalized_type,
            source_filename=filename,
            total_rows=len(frame),
            issues=tuple(issues),
        )

    def validate(
        self,
        dataset_type: DatasetType | str,
        data: DatasetInput,
        *,
        source_filename: str | None = None,
        products: DatasetInput | None = None,
        orders: DatasetInput | None = None,
    ) -> DatasetValidationResult:
        """Concise alias for :meth:`validate_dataset`."""
        return self.validate_dataset(
            dataset_type,
            data,
            source_filename=source_filename,
            products=products,
            orders=orders,
        )

    def validate_orders(
        self, data: DatasetInput, *, source_filename: str | None = None
    ) -> DatasetValidationResult:
        return self.validate_dataset(DatasetType.ORDERS, data, source_filename=source_filename)

    def validate_products(
        self, data: DatasetInput, *, source_filename: str | None = None
    ) -> DatasetValidationResult:
        return self.validate_dataset(DatasetType.PRODUCTS, data, source_filename=source_filename)

    def validate_inventory(
        self,
        data: DatasetInput,
        *,
        products: DatasetInput | None = None,
        source_filename: str | None = None,
    ) -> DatasetValidationResult:
        return self.validate_dataset(
            DatasetType.INVENTORY,
            data,
            products=products,
            source_filename=source_filename,
        )

    def validate_returns(
        self,
        data: DatasetInput,
        *,
        orders: DatasetInput | None = None,
        products: DatasetInput | None = None,
        source_filename: str | None = None,
    ) -> DatasetValidationResult:
        return self.validate_dataset(
            DatasetType.RETURNS,
            data,
            orders=orders,
            products=products,
            source_filename=source_filename,
        )

    def validate_targets(
        self, data: DatasetInput, *, source_filename: str | None = None
    ) -> DatasetValidationResult:
        return self.validate_dataset(
            DatasetType.MONTHLY_TARGETS,
            data,
            source_filename=source_filename,
        )

    def validate_all(
        self,
        datasets: Mapping[DatasetType | str, DatasetInput],
        *,
        source_filenames: Mapping[DatasetType | str, str] | None = None,
    ) -> CombinedValidationResult:
        """Validate supplied datasets and automatically apply reference checks."""
        normalized = {_dataset_type(key): value for key, value in datasets.items()}
        filenames = {_dataset_type(key): value for key, value in (source_filenames or {}).items()}
        products = normalized.get(DatasetType.PRODUCTS)
        orders = normalized.get(DatasetType.ORDERS)
        results: list[DatasetValidationResult] = []
        for dataset_type in DatasetType:
            data = normalized.get(dataset_type)
            if data is None:
                continue
            results.append(
                self.validate_dataset(
                    dataset_type,
                    data,
                    source_filename=filenames.get(dataset_type),
                    products=(
                        products
                        if dataset_type in {DatasetType.INVENTORY, DatasetType.RETURNS}
                        else None
                    ),
                    orders=orders if dataset_type is DatasetType.RETURNS else None,
                )
            )
        return CombinedValidationResult(tuple(results))


def export_issues_dataframe(
    result: DatasetValidationResult | CombinedValidationResult,
) -> pd.DataFrame:
    """Export every issue from a validation result as a flat DataFrame."""
    return issues_to_dataframe(result.issues)
