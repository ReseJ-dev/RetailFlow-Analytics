"""Authenticated, paginated REST ingestion for RetailFlow datasets."""

from __future__ import annotations

import logging
from collections.abc import Callable
from time import sleep

import pandas as pd
import requests
from pydantic import ValidationError

from retailflow.common.exceptions import DataSourceError
from retailflow.ingestion.api_models import ApiHealth, ApiPage
from retailflow.ingestion.models import FileMetadata, LoadedDataset
from retailflow.ingestion.retry import RetryPolicy
from retailflow.validation import DatasetType, get_dataset_schema

logger = logging.getLogger("retailflow.ingestion.api")


class ApiClientError(DataSourceError):
    """Base class for user-safe API ingestion failures."""


class ApiAuthenticationError(ApiClientError):
    """Raised for invalid or unauthorized credentials without retrying."""


class ApiRequestError(ApiClientError):
    """Raised for non-retryable client requests."""


class ApiRateLimitError(ApiClientError):
    """Raised when rate-limit retries are exhausted."""


class ApiServerError(ApiClientError):
    """Raised when a temporary server failure persists."""


class ApiResponseError(ApiClientError):
    """Raised when an API response is not valid JSON."""


class ApiSchemaError(ApiClientError):
    """Raised when JSON does not match its envelope or dataset schema."""


class ApiCancelledError(ApiClientError):
    """Raised when a caller cancels pagination or retry waiting."""


type CancellationCallback = Callable[[], bool]
type SleepCallback = Callable[[float], None]

_ENDPOINTS = {
    DatasetType.ORDERS: "orders",
    DatasetType.PRODUCTS: "products",
    DatasetType.INVENTORY: "inventory",
    DatasetType.RETURNS: "returns",
}


class RetailApiClient:
    """Load authenticated API pages into the common LoadedDataset model."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        connect_timeout: float = 3.0,
        read_timeout: float = 20.0,
        retry_count: int = 3,
        backoff_factor: float = 0.5,
        page_size: int = 100,
        session: requests.Session | None = None,
        sleep_callback: SleepCallback = sleep,
        cancellation_callback: CancellationCallback | None = None,
    ) -> None:
        """Configure endpoint, credentials, timeouts, pagination, and retry behavior."""
        if not base_url.strip():
            raise ApiRequestError("The Retail API URL is required.")
        if not token.strip():
            raise ApiAuthenticationError("The Retail API token is required.")
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ApiRequestError("API timeouts must be greater than zero.")
        if page_size <= 0:
            raise ApiRequestError("API page size must be greater than zero.")
        if retry_count < 0 or backoff_factor < 0:
            raise ApiRequestError("API retry settings cannot be negative.")
        self.base_url = base_url.rstrip("/")
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.page_size = page_size
        self.retry_policy = RetryPolicy(retry_count, backoff_factor)
        self._session = session or requests.Session()
        self._owns_session = session is None
        self._sleep = sleep_callback
        self._cancelled = cancellation_callback or (lambda: False)
        # Authorization is kept only in the in-memory HTTP session and is never logged.
        self._session.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )

    def __enter__(self) -> RetailApiClient:
        """Return this client for context-managed usage."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close an internally-owned HTTP session."""
        self.close()

    def close(self) -> None:
        """Close the internally-created HTTP session."""
        if self._owns_session:
            self._session.close()

    def test_connection(self) -> ApiHealth:
        """Authenticate against the health endpoint and validate its response."""
        response = self._request_json("/api/health", params=None)
        try:
            return ApiHealth.model_validate(response)
        except ValidationError as error:
            raise ApiSchemaError(
                "The Retail API health response has an unexpected schema.",
                technical_detail=str(error),
            ) from error

    def load_all(self) -> dict[DatasetType, LoadedDataset]:
        """Load all four required API datasets without mixing file sources."""
        return {dataset_type: self.load_dataset(dataset_type) for dataset_type in _ENDPOINTS}

    def load_dataset(self, dataset_type: DatasetType | str) -> LoadedDataset:
        """Load and validate every page for one supported dataset."""
        try:
            normalized = DatasetType(dataset_type)
        except ValueError as error:
            raise ApiRequestError(
                f"Dataset '{dataset_type}' is not available from the API."
            ) from error
        if normalized not in _ENDPOINTS:
            raise ApiRequestError(f"Dataset '{normalized.value}' is not available from the API.")
        endpoint = _ENDPOINTS[normalized]
        page_number: int | None = 1
        records: list[dict[str, object]] = []
        columns: tuple[str, ...] | None = None
        total = 0
        response_bytes = 0
        visited: set[int] = set()
        while page_number is not None:
            self._check_cancelled()
            if page_number in visited:
                raise ApiSchemaError("The Retail API returned a pagination loop.")
            visited.add(page_number)
            payload, payload_size = self._request_json_with_size(
                f"/api/{endpoint}",
                params={"page": page_number, "page_size": self.page_size},
            )
            response_bytes += payload_size
            try:
                page = ApiPage.model_validate(payload)
            except ValidationError as error:
                raise ApiSchemaError(
                    f"The {normalized.value} API response has an unexpected schema.",
                    technical_detail=str(error),
                ) from error
            if page.page != page_number:
                raise ApiSchemaError(
                    f"The {normalized.value} API returned an unexpected page number."
                )
            if columns is None:
                columns = page.columns
                total = page.total
                self._validate_columns(normalized, columns)
            elif page.columns != columns or page.total != total:
                raise ApiSchemaError(
                    f"The {normalized.value} API changed schema during pagination."
                )
            records.extend(page.items)
            page_number = page.next_page
            logger.info(
                "Loaded API page for %s with %d records",
                normalized.value,
                len(page.items),
            )
        if columns is None or len(records) != total:
            raise ApiSchemaError(
                f"The {normalized.value} API returned an inconsistent total row count."
            )
        dataframe = pd.DataFrame.from_records(records, columns=columns)
        return LoadedDataset(
            dataframe=dataframe,
            metadata=FileMetadata(
                filename=f"api_{normalized.value}.json",
                file_type="api",
                file_size=response_bytes,
                row_count=len(dataframe),
                column_count=len(columns),
                columns=columns,
            ),
        )

    @staticmethod
    def _validate_columns(dataset_type: DatasetType, columns: tuple[str, ...]) -> None:
        required = set(get_dataset_schema(dataset_type).required_columns)
        missing = sorted(required - set(columns))
        if missing:
            raise ApiSchemaError(
                f"The {dataset_type.value} API response is missing required fields: "
                f"{', '.join(missing)}."
            )

    def _request_json(
        self, endpoint: str, *, params: dict[str, int] | None
    ) -> object:
        return self._request_json_with_size(endpoint, params=params)[0]

    def _request_json_with_size(
        self, endpoint: str, *, params: dict[str, int] | None
    ) -> tuple[object, int]:
        response = self._request(endpoint, params=params)
        try:
            return response.json(), len(response.content)
        except (requests.exceptions.InvalidJSONError, ValueError) as error:
            raise ApiResponseError(
                "The Retail API returned invalid JSON.",
                technical_detail=f"Endpoint: {endpoint}; {error}",
            ) from error

    def _request(
        self, endpoint: str, *, params: dict[str, int] | None
    ) -> requests.Response:
        url = f"{self.base_url}{endpoint}"
        attempts = self.retry_policy.retry_count + 1
        for attempt in range(1, attempts + 1):
            self._check_cancelled()
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=(self.connect_timeout, self.read_timeout),
                )
            except (requests.Timeout, requests.ConnectionError) as error:
                if attempt >= attempts:
                    raise ApiRequestError(
                        "The Retail API could not be reached after retrying.",
                        technical_detail=f"Endpoint: {endpoint}; {type(error).__name__}",
                    ) from error
                self._wait(attempt)
                continue
            status = response.status_code
            if 200 <= status < 300:
                return response
            if status in {401, 403}:
                raise ApiAuthenticationError(
                    "The Retail API credentials were rejected.",
                    technical_detail=f"Endpoint: {endpoint}; status: {status}",
                )
            if status in self.retry_policy.retry_statuses:
                if attempt < attempts:
                    self._wait(attempt, response.headers.get("Retry-After"))
                    continue
                if status == 429:
                    raise ApiRateLimitError(
                        "The Retail API rate limit was reached. Try again later.",
                        technical_detail=f"Endpoint: {endpoint}; status: 429",
                    )
                raise ApiServerError(
                    "The Retail API is temporarily unavailable after retrying.",
                    technical_detail=f"Endpoint: {endpoint}; status: {status}",
                )
            if 400 <= status < 500:
                raise ApiRequestError(
                    "The Retail API rejected the request.",
                    technical_detail=f"Endpoint: {endpoint}; status: {status}",
                )
            raise ApiServerError(
                "The Retail API returned an unexpected server response.",
                technical_detail=f"Endpoint: {endpoint}; status: {status}",
            )
        raise ApiRequestError("The Retail API request could not be completed.")

    def _wait(self, retry_number: int, retry_after: str | None = None) -> None:
        self._check_cancelled()
        self._sleep(self.retry_policy.delay(retry_number, retry_after))
        self._check_cancelled()

    def _check_cancelled(self) -> None:
        if self._cancelled():
            raise ApiCancelledError("The Retail API request was cancelled.")


__all__ = [
    "ApiAuthenticationError",
    "ApiCancelledError",
    "ApiClientError",
    "ApiRateLimitError",
    "ApiRequestError",
    "ApiResponseError",
    "ApiSchemaError",
    "ApiServerError",
    "RetailApiClient",
]
