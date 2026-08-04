"""Validated models shared by the REST API ingestion client."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApiPage(BaseModel):
    """One validated page of API records and pagination metadata."""

    model_config = ConfigDict(extra="forbid")

    items: list[dict[str, Any]]
    columns: tuple[str, ...] = Field(min_length=1)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    next_page: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_pagination(self) -> ApiPage:
        """Reject inconsistent counts and non-advancing pagination."""
        if len(self.items) > self.page_size:
            raise ValueError("items cannot exceed page_size")
        if self.next_page is not None and self.next_page <= self.page:
            raise ValueError("next_page must advance pagination")
        expected_columns = set(self.columns)
        if any(set(item) != expected_columns for item in self.items):
            raise ValueError("every item must match the advertised columns")
        return self


class ApiHealth(BaseModel):
    """Mock API health response."""

    model_config = ConfigDict(extra="forbid")

    status: str
    service: str


__all__ = ["ApiHealth", "ApiPage"]
