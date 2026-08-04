"""FastAPI application serving deterministic demonstration retail data."""

from __future__ import annotations

import os
import secrets
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from mock_api.schemas import HealthResponse, PaginatedResponse

DEMO_TOKEN = "retailflow-demo-token"
security = HTTPBearer(auto_error=False)
app = FastAPI(
    title="RetailFlow Demonstration API",
    version="0.1.0",
    description="Local authenticated and paginated source data for RetailFlow demos.",
)

ORDERS = (
    {
        "order_id": "O-1001",
        "order_date": "2026-01-05",
        "customer_id": "C-001",
        "product_id": "P-001",
        "quantity": 2,
        "unit_price": 45.0,
        "discount": 0.1,
        "currency": "USD",
        "country": "Cyprus",
        "sales_channel": "Website",
        "order_status": "completed",
    },
    {
        "order_id": "O-1002",
        "order_date": "2026-01-08",
        "customer_id": "C-002",
        "product_id": "P-002",
        "quantity": 1,
        "unit_price": 80.0,
        "discount": 0.0,
        "currency": "USD",
        "country": "Germany",
        "sales_channel": "Amazon",
        "order_status": "completed",
    },
    {
        "order_id": "O-1003",
        "order_date": "2026-01-12",
        "customer_id": "C-003",
        "product_id": "P-001",
        "quantity": 1,
        "unit_price": 45.0,
        "discount": 0.0,
        "currency": "USD",
        "country": "France",
        "sales_channel": "Marketplace",
        "order_status": "pending",
    },
)
PRODUCTS = (
    {
        "product_id": "P-001",
        "product_name": "Compact Office Set",
        "category": "Office",
        "supplier": "Demo Supplier A",
        "purchase_cost": 20.0,
        "recommended_price": 45.0,
        "vat_rate": 0.19,
    },
    {
        "product_id": "P-002",
        "product_name": "Travel Electronics Kit",
        "category": "Electronics",
        "supplier": "Demo Supplier B",
        "purchase_cost": 42.0,
        "recommended_price": 80.0,
        "vat_rate": 0.19,
    },
)
INVENTORY = (
    {
        "product_id": "P-001",
        "warehouse": "Nicosia",
        "stock_quantity": 12,
        "reserved_quantity": 2,
        "reorder_level": 8,
        "last_restock_date": "2025-12-20",
    },
    {
        "product_id": "P-002",
        "warehouse": "Berlin",
        "stock_quantity": 4,
        "reserved_quantity": 1,
        "reorder_level": 5,
        "last_restock_date": "2025-12-28",
    },
)
RETURNS = (
    {
        "return_id": "R-001",
        "order_id": "O-1001",
        "product_id": "P-001",
        "return_date": "2026-01-10",
        "quantity": 1,
        "return_reason": "Damaged in transit",
        "refund_amount": 40.5,
    },
)


def _expected_token() -> str:
    return os.getenv("RETAIL_API_TOKEN", DEMO_TOKEN)


def require_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> None:
    """Require the configured bearer token without logging its value."""
    if (
        credentials is None
        or credentials.scheme.casefold() != "bearer"
        or not secrets.compare_digest(credentials.credentials, _expected_token())
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _paginate(
    records: Sequence[dict[str, object]],
    *,
    page: int,
    page_size: int,
) -> PaginatedResponse:
    columns = tuple(records[0]) if records else ("id",)
    start = (page - 1) * page_size
    end = start + page_size
    items = list(records[start:end])
    next_page = page + 1 if end < len(records) else None
    return PaginatedResponse(
        items=items,
        columns=columns,
        page=page,
        page_size=page_size,
        total=len(records),
        next_page=next_page,
    )


Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=500)]
Authentication = Annotated[None, Depends(require_token)]


@app.get("/api/health", response_model=HealthResponse)
def health(_: Authentication) -> HealthResponse:
    """Return authenticated API availability."""
    return HealthResponse(status="ok", service="retailflow-mock-api")


@app.get("/api/orders", response_model=PaginatedResponse)
def orders(_: Authentication, page: Page = 1, page_size: PageSize = 100) -> PaginatedResponse:
    """Return a page of demonstration orders."""
    return _paginate(ORDERS, page=page, page_size=page_size)


@app.get("/api/products", response_model=PaginatedResponse)
def products(_: Authentication, page: Page = 1, page_size: PageSize = 100) -> PaginatedResponse:
    """Return a page of demonstration products."""
    return _paginate(PRODUCTS, page=page, page_size=page_size)


@app.get("/api/inventory", response_model=PaginatedResponse)
def inventory(_: Authentication, page: Page = 1, page_size: PageSize = 100) -> PaginatedResponse:
    """Return a page of demonstration inventory."""
    return _paginate(INVENTORY, page=page, page_size=page_size)


@app.get("/api/returns", response_model=PaginatedResponse)
def returns(_: Authentication, page: Page = 1, page_size: PageSize = 100) -> PaginatedResponse:
    """Return a page of demonstration returns."""
    return _paginate(RETURNS, page=page, page_size=page_size)


__all__ = ["DEMO_TOKEN", "app"]
