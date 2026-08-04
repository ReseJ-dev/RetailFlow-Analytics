"""ASGI integration tests for the local demonstration API and API client."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from mock_api.main import DEMO_TOKEN, app

from retailflow.cli_helpers import process_loaded_datasets
from retailflow.common.config import RetailFlowSettings
from retailflow.ingestion.api_client import RetailApiClient
from retailflow.validation import DatasetType


class AsgiSession:
    """Adapt FastAPI's test client to the small requests.Session surface used."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.headers: dict[str, str] = {}

    def get(
        self,
        url: str,
        *,
        params: dict[str, int] | None,
        timeout: tuple[float, float],
    ) -> Any:
        del timeout
        return self.client.get(
            urlparse(url).path,
            params=params,
            headers=self.headers,
        )

    def close(self) -> None:
        """Match requests.Session.close."""


@pytest.fixture
def api() -> TestClient:
    """Return an in-process client for the mock API."""
    return TestClient(app)


def test_mock_api_requires_bearer_authentication(api: TestClient) -> None:
    assert api.get("/api/health").status_code == 401
    response = api.get(
        "/api/health",
        headers={"Authorization": f"Bearer {DEMO_TOKEN}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_empty_container_token_configuration_uses_documented_demo_token(
    api: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RETAIL_API_TOKEN", "")

    response = api.get(
        "/api/health",
        headers={"Authorization": f"Bearer {DEMO_TOKEN}"},
    )

    assert response.status_code == 200


def test_mock_api_exposes_pagination_metadata(api: TestClient) -> None:
    response = api.get(
        "/api/orders",
        params={"page": 1, "page_size": 1},
        headers={"Authorization": f"Bearer {DEMO_TOKEN}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 1
    assert payload["total"] == 3
    assert payload["next_page"] == 2
    assert len(payload["items"]) == 1


def test_api_client_loads_all_mock_api_datasets(api: TestClient) -> None:
    session = AsgiSession(api)
    client = RetailApiClient(
        "http://testserver",
        DEMO_TOKEN,
        page_size=1,
        session=session,  # type: ignore[arg-type]
        sleep_callback=lambda _: None,
    )

    datasets = client.load_all()

    assert set(datasets) == {
        DatasetType.ORDERS,
        DatasetType.PRODUCTS,
        DatasetType.INVENTORY,
        DatasetType.RETURNS,
    }
    assert datasets[DatasetType.ORDERS].row_count == 3
    assert datasets[DatasetType.PRODUCTS].row_count == 2
    assert all(dataset.file_type == "api" for dataset in datasets.values())

    processing = process_loaded_datasets(datasets, RetailFlowSettings())
    assert len(processing.processed_orders) == 3
    assert processing.excluded_rows.empty
