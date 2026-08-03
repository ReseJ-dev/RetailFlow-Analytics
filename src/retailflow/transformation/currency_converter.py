"""Injectable, deterministic currency conversion without external I/O."""

from __future__ import annotations

from collections.abc import Mapping

from retailflow.transformation.normalizer import normalize_currency


class UnsupportedCurrencyError(ValueError):
    """Raised when no injected rate exists for a source currency."""


class CurrencyConverter:
    """Convert currencies using rates expressed in units of the default currency."""

    def __init__(
        self,
        default_currency: str = "USD",
        exchange_rates: Mapping[str, float] | None = None,
    ) -> None:
        normalized_default = normalize_currency(default_currency)
        if not isinstance(normalized_default, str):
            raise ValueError("default_currency must not be empty")
        self.default_currency = normalized_default
        self._rates = {
            str(code).strip().upper(): float(rate) for code, rate in (exchange_rates or {}).items()
        }
        self._rates[self.default_currency] = 1.0
        if any(rate <= 0 for rate in self._rates.values()):
            raise ValueError("exchange rates must be greater than zero")

    @property
    def supported_currencies(self) -> frozenset[str]:
        return frozenset(self._rates)

    def supports(self, currency: object) -> bool:
        normalized = normalize_currency(currency)
        return isinstance(normalized, str) and normalized in self._rates

    def convert(self, amount: float, currency: object) -> float:
        normalized = normalize_currency(currency)
        if not isinstance(normalized, str) or normalized not in self._rates:
            raise UnsupportedCurrencyError(f"Unsupported currency: {currency!r}")
        return float(amount) * self._rates[normalized]
