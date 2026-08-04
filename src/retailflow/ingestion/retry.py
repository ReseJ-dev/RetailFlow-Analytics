"""Retry policy and Retry-After parsing for REST ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential retry settings for temporary API failures."""

    retry_count: int = 3
    backoff_factor: float = 0.5
    retry_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504})

    def __post_init__(self) -> None:
        if self.retry_count < 0:
            raise ValueError("retry_count cannot be negative")
        if self.backoff_factor < 0:
            raise ValueError("backoff_factor cannot be negative")

    def delay(self, retry_number: int, retry_after: str | None = None) -> float:
        """Return Retry-After seconds when valid, otherwise exponential backoff."""
        parsed = parse_retry_after(retry_after)
        if parsed is not None:
            return parsed
        return float(self.backoff_factor * (2 ** max(0, retry_number - 1)))


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Parse delta-seconds or an HTTP date into a non-negative delay."""
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        current = now or datetime.now(UTC)
        return max(0.0, (target - current).total_seconds())


__all__ = ["RetryPolicy", "parse_retry_after"]
