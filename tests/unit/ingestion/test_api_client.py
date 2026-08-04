"""Tests for authenticated, paginated REST ingestion."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import pytest
import requests

from retailflow.ingestion.api_client import (
    ApiAuthenticationError,
    ApiRateLimitError,
    ApiResponseError,
    ApiSchemaError,
    RetailApiClient,
)
from retailflow.validation import DatasetType

ORDER_COLUMNS = (
    "order_id",
    "order_date",
    "product_id",
    "quantity",
    "unit_price",
)


def _response(
    status_code: int,
    payload: object | None = None,
    *,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.headers.update(headers or {})
    response._content = content if content is not None else json.dumps(payload).encode()
    response.encoding = "utf-8"
    return response


def _order_page(
    *,
    page: int = 1,
    total: int = 1,
    next_page: int | None = None,
    order_id: str = "O-1",
) -> dict[str, object]:
    return {
        "items": [
            {
                "order_id": order_id,
                "order_date": "2026-01-01",
                "product_id": "P-1",
                "quantity": 1,
                "unit_price": 10.0,
            }
        ],
        "columns": list(ORDER_COLUMNS),
        "page": page,
        "page_size": 1,
        "total": total,
        "next_page": next_page,
    }


class FakeSession:
    """Minimal requests-compatible session backed by queued outcomes."""

    def __init__(self, outcomes: list[requests.Response | Exception]) -> None:
        self.headers: dict[str, str] = {}
        self.outcomes = outcomes
        self.calls = 0

    def get(self, *_: object, **__: object) -> requests.Response:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self) -> None:
        """Match requests.Session.close."""


def _client(
    session: FakeSession,
    *,
    retry_count: int = 2,
    sleep_callback: Callable[[float], None] = lambda _: None,
    token: str = "test-token",
) -> RetailApiClient:
    return RetailApiClient(
        "https://retail.example",
        token,
        page_size=1,
        retry_count=retry_count,
        backoff_factor=0,
        session=session,  # type: ignore[arg-type]
        sleep_callback=sleep_callback,
    )


def test_load_dataset_follows_successful_pagination() -> None:
    session = FakeSession(
        [
            _response(200, _order_page(total=2, next_page=2, order_id="O-1")),
            _response(200, _order_page(page=2, total=2, order_id="O-2")),
        ]
    )

    loaded = _client(session).load_dataset(DatasetType.ORDERS)

    assert loaded.row_count == 2
    assert loaded.file_type == "api"
    assert loaded.dataframe["order_id"].tolist() == ["O-1", "O-2"]
    assert session.calls == 2


def test_timeout_is_retried() -> None:
    session = FakeSession(
        [requests.Timeout("temporary"), _response(200, _order_page())]
    )

    loaded = _client(session).load_dataset(DatasetType.ORDERS)

    assert loaded.row_count == 1
    assert session.calls == 2


def test_500_is_retried() -> None:
    session = FakeSession([_response(500, {}), _response(200, _order_page())])

    _client(session).load_dataset(DatasetType.ORDERS)

    assert session.calls == 2


def test_401_is_not_retried() -> None:
    session = FakeSession([_response(401, {})])

    with pytest.raises(ApiAuthenticationError):
        _client(session).load_dataset(DatasetType.ORDERS)

    assert session.calls == 1


def test_429_respects_retry_after() -> None:
    delays: list[float] = []
    session = FakeSession(
        [
            _response(429, {}, headers={"Retry-After": "2"}),
            _response(200, _order_page()),
        ]
    )

    _client(session, sleep_callback=delays.append).load_dataset(DatasetType.ORDERS)

    assert delays == [2.0]
    assert session.calls == 2


def test_exhausted_429_raises_rate_limit_error() -> None:
    session = FakeSession([_response(429, {})])

    with pytest.raises(ApiRateLimitError):
        _client(session, retry_count=0).load_dataset(DatasetType.ORDERS)


def test_invalid_json_is_not_retried() -> None:
    session = FakeSession([_response(200, content=b"not-json")])

    with pytest.raises(ApiResponseError):
        _client(session).load_dataset(DatasetType.ORDERS)

    assert session.calls == 1


def test_schema_mismatch_is_not_retried() -> None:
    invalid_page = _order_page()
    invalid_page["columns"] = ["order_id"]
    invalid_page["items"] = [{"order_id": "O-1"}]
    session = FakeSession([_response(200, invalid_page)])

    with pytest.raises(ApiSchemaError, match="missing required fields"):
        _client(session).load_dataset(DatasetType.ORDERS)

    assert session.calls == 1


def test_token_is_never_logged_or_exposed_in_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "do-not-log-this-token"
    session = FakeSession([_response(401, {})])
    caplog.set_level(logging.DEBUG)

    with pytest.raises(ApiAuthenticationError) as caught:
        _client(session, token=secret).load_dataset(DatasetType.ORDERS)

    assert secret not in caplog.text
    assert secret not in str(caught.value)
    assert secret not in str(caught.value.technical_detail)
    assert session.headers["Authorization"] == f"Bearer {secret}"


def test_response_payload_never_requires_complete_records_in_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = FakeSession([_response(200, _order_page(order_id="PRIVATE-ORDER"))])
    caplog.set_level(logging.INFO, logger="retailflow.ingestion.api")

    _client(session).load_dataset(DatasetType.ORDERS)

    assert "PRIVATE-ORDER" not in caplog.text


def test_health_response_is_schema_validated() -> None:
    session = FakeSession([_response(200, {"status": "ok", "service": "mock"})])

    health = _client(session).test_connection()

    assert health.status == "ok"


@pytest.mark.parametrize("invalid_payload", [{}, {"items": "invalid"}])
def test_invalid_envelope_raises_schema_error(invalid_payload: dict[str, Any]) -> None:
    session = FakeSession([_response(200, invalid_payload)])

    with pytest.raises(ApiSchemaError):
        _client(session).load_dataset(DatasetType.ORDERS)
