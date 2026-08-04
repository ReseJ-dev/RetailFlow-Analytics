"""Streamlit-facing API source operations without retaining credentials."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

import pandas as pd

from retailflow.common.exceptions import RetailFlowError
from retailflow.ingestion import LoadedDataset, RetailApiClient
from retailflow.validation import DatasetType

logger = logging.getLogger("retailflow.app.api_source")


def test_api_connection(
    api_url: str,
    token: str,
    *,
    client_factory: type[RetailApiClient] = RetailApiClient,
) -> str:
    """Test authenticated health without storing or logging the bearer token."""
    try:
        with client_factory(api_url, token) as client:
            health = client.test_connection()
    except RetailFlowError:
        logger.exception("Retail API connection test failed")
        raise
    logger.info("Retail API connection test succeeded for configured endpoint")
    return health.status


def load_api_datasets(
    api_url: str,
    token: str,
    *,
    cancellation_callback: Callable[[], bool] | None = None,
    client_factory: type[RetailApiClient] = RetailApiClient,
) -> dict[str, LoadedDataset]:
    """Load all required API sources and return session-compatible dataset keys."""
    try:
        with client_factory(
            api_url,
            token,
            cancellation_callback=cancellation_callback,
        ) as client:
            loaded = client.load_all()
    except RetailFlowError:
        logger.exception("Retail API dataset loading failed")
        raise
    logger.info(
        "Loaded %d API datasets containing %d total rows",
        len(loaded),
        sum(dataset.row_count for dataset in loaded.values()),
    )
    return {dataset_type.value: dataset for dataset_type, dataset in loaded.items()}


def source_summary(datasets: Mapping[str, LoadedDataset]) -> pd.DataFrame:
    """Build source-level counts without exposing full API records."""
    return pd.DataFrame.from_records(
        [
            {
                "Dataset": name,
                "Source": dataset.filename,
                "Type": dataset.file_type,
                "Rows": dataset.row_count,
                "Columns": dataset.column_count,
            }
            for name, dataset in datasets.items()
        ]
    )


REQUIRED_API_DATASETS = tuple(dataset_type.value for dataset_type in (
    DatasetType.ORDERS,
    DatasetType.PRODUCTS,
    DatasetType.INVENTORY,
    DatasetType.RETURNS,
))

__all__ = [
    "REQUIRED_API_DATASETS",
    "load_api_datasets",
    "source_summary",
    "test_api_connection",
]
