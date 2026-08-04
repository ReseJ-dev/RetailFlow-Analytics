"""Worksheet builders and their shared report context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from retailflow.analytics.models import (
    PeriodComparison,
    ReturnsAnalyticsResult,
    SalesAnalyticsResult,
)
from retailflow.models import ProcessingResult
from retailflow.reporting.formatting import ReportFormats, ReportVisualThresholds


@dataclass(frozen=True, slots=True)
class WorksheetContext:
    """Immutable data supplied to every report worksheet builder."""

    processing: ProcessingResult
    sales: SalesAnalyticsResult
    returns: ReturnsAnalyticsResult
    inventory_analytics: pd.DataFrame
    recommendations: pd.DataFrame
    formats: ReportFormats
    company_name: str
    default_currency: str
    report_id: str
    generated_at: datetime
    application_version: str
    reporting_period: str
    prepared_by: str
    report_title: str = "RetailFlow Analytics Management Report"
    included_worksheets: tuple[str, ...] = ()
    logo_path: Path | None = None
    previous_sales: SalesAnalyticsResult | None = None
    period_comparison: PeriodComparison | None = None
    visual_thresholds: ReportVisualThresholds = ReportVisualThresholds()


__all__ = ["WorksheetContext"]
