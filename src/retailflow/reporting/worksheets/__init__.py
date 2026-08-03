"""Worksheet builders and their shared report context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from retailflow.analytics.models import ReturnsAnalyticsResult, SalesAnalyticsResult
from retailflow.models import ProcessingResult
from retailflow.reporting.formatting import ReportFormats


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


__all__ = ["WorksheetContext"]
