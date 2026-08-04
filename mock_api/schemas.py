"""FastAPI response schemas for the local demonstration source."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PaginatedResponse(BaseModel):
    """Stable paginated response returned by every dataset endpoint."""

    model_config = ConfigDict(extra="forbid")

    items: list[dict[str, Any]]
    columns: tuple[str, ...] = Field(min_length=1)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    next_page: int | None = Field(default=None, ge=1)


class HealthResponse(BaseModel):
    """Health response for authenticated connection tests."""

    status: str
    service: str


__all__ = ["HealthResponse", "PaginatedResponse"]
