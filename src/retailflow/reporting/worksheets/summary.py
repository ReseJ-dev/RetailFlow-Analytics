"""Executive dashboard worksheet builder."""

import pandas as pd
from xlsxwriter.format import Format
from xlsxwriter.workbook import Workbook
from xlsxwriter.worksheet import Worksheet

from retailflow.analytics.models import MetricComparison
from retailflow.reporting.chart_builder import (
    ChartSeries,
    add_column_chart,
    add_line_chart,
)
from retailflow.reporting.formatting import (
    apply_worksheet_defaults,
    configure_print_layout,
    write_dataframe_table,
    write_internal_link,
    write_section_header,
    write_title,
)
from retailflow.reporting.worksheets import WorksheetContext

_CARDS = (
    ("net_revenue", "Net Revenue", "currency"),
    ("gross_profit", "Gross Profit", "currency"),
    ("gross_margin_percent", "Gross Margin", "percentage"),
    ("orders", "Orders", "integer"),
    ("average_order_value", "Average Order Value", "currency"),
    ("return_rate_percent", "Return Rate", "percentage"),
)


def _comparison_text(metric: MetricComparison | None, *, rate: bool) -> str:
    if metric is None:
        return "No previous-period data is available for comparison."
    difference = metric.percentage_point_difference if rate else metric.percentage_difference
    if difference is None:
        return "Previous period was zero"
    suffix = " pp" if rate else "%"
    return f"{float(difference):+.1f}{suffix} vs previous period"


def _comparison_format(
    context: WorksheetContext,
    metric: MetricComparison | None,
    *,
    inverse: bool,
) -> Format:
    if metric is None:
        return context.formats.card_neutral
    difference = metric.percentage_point_difference or metric.percentage_difference
    if difference is None or difference == 0:
        return context.formats.card_neutral
    improved = difference < 0 if inverse else difference > 0
    return context.formats.card_positive if improved else context.formats.card_negative


def _write_kpi_cards(worksheet: Worksheet, context: WorksheetContext) -> None:
    for index, (field, label, kind) in enumerate(_CARDS):
        card_row = 3 + (index // 3) * 4
        card_column = (index % 3) * 4
        worksheet.merge_range(
            card_row,
            card_column,
            card_row,
            card_column + 2,
            label,
            context.formats.card_title,
        )
        value = getattr(context.sales.kpis, field)
        value_format = {
            "currency": context.formats.card_currency,
            "percentage": context.formats.card_percentage,
            "integer": context.formats.card_integer,
        }[kind]
        worksheet.merge_range(
            card_row + 1,
            card_column,
            card_row + 1,
            card_column + 2,
            float(value),
            value_format,
        )
        comparison = (
            context.period_comparison.metrics.get(field)
            if context.period_comparison is not None
            else None
        )
        worksheet.merge_range(
            card_row + 2,
            card_column,
            card_row + 2,
            card_column + 2,
            _comparison_text(comparison, rate=field.endswith("_percent")),
            _comparison_format(
                context,
                comparison,
                inverse=field == "return_rate_percent",
            ),
        )


def _revenue_trend(context: WorksheetContext) -> pd.DataFrame:
    current = context.sales.daily_revenue
    if current.empty:
        return current.copy()
    frame = current.loc[:, ["date", "net_revenue"]].rename(
        columns={"net_revenue": "current_period_revenue"}
    )
    if context.previous_sales is not None and not context.previous_sales.daily_revenue.empty:
        previous = context.previous_sales.daily_revenue["net_revenue"].reset_index(drop=True)
        frame = frame.reset_index(drop=True)
        frame["previous_period_revenue"] = previous.reindex(frame.index)
    return frame


def _target_achievement(context: WorksheetContext) -> pd.DataFrame:
    targets = context.processing.targets.copy()
    orders = context.sales.enriched_orders
    if targets.empty or "month" not in targets or orders.empty or "order_date" not in orders:
        return targets.iloc[0:0]
    actual = orders.copy()
    actual["month"] = pd.to_datetime(actual["order_date"], errors="coerce").dt.strftime("%Y-%m")
    monthly_actual = actual.groupby("month", as_index=False).agg(net_revenue=("net_revenue", "sum"))
    frame = targets.merge(monthly_actual, on="month", how="left")
    frame["actual_revenue"] = frame.pop("net_revenue").fillna(0.0)
    frame["target_achievement"] = pd.to_numeric(
        frame["actual_revenue"], errors="coerce"
    ) / pd.to_numeric(frame["revenue_target"], errors="coerce").replace(0, pd.NA)
    return frame


def write_summary_worksheet(
    workbook: Workbook, worksheet: Worksheet, context: WorksheetContext
) -> int:
    """Write a polished executive dashboard with actionable drill-downs."""
    apply_worksheet_defaults(worksheet, context.formats)
    write_title(worksheet, "Executive Summary", context.formats)
    worksheet.write(1, 0, context.reporting_period, context.formats.subtitle)
    for cell, target, label in (
        ("E2", "02_Sales_Analysis", "View Sales Analysis"),
        ("G2", "03_Product_Performance", "View Product Detail"),
        ("I2", "04_Inventory", "View Inventory Details"),
        ("K2", "05_Returns", "View Returns Detail"),
    ):
        if target in context.included_worksheets:
            write_internal_link(worksheet, cell, target, label, context.formats)
    _write_kpi_cards(worksheet, context)
    worksheet.set_column("A:L", 15)

    row = 11
    trend = _revenue_trend(context)
    write_section_header(worksheet, row, "Revenue Trend", context.formats)
    trend_start = row + 1
    row = write_dataframe_table(
        worksheet,
        trend,
        trend_start,
        0,
        context.formats,
        "SummaryRevenueTrend",
        empty_message="No revenue was recorded during the selected period.",
    )
    series = [ChartSeries("Current period", 1)]
    if "previous_period_revenue" in trend:
        series.append(ChartSeries("Previous period", 2, context.formats.theme.neutral))
    add_line_chart(
        workbook,
        worksheet,
        sheet_name="01_Executive_Summary",
        first_data_row=trend_start + 1,
        last_data_row=trend_start + len(trend),
        category_column=0,
        series=series if not trend.empty else (),
        title="Current vs Previous Revenue",
        position="E13",
        currency_axis=context.default_currency,
        theme=context.formats.theme,
    )
    row = max(row, 29)

    category = context.sales.category_performance.head(10)
    write_section_header(worksheet, row, "Category Performance", context.formats)
    category_start = row + 1
    row = write_dataframe_table(
        worksheet, category, category_start, 0, context.formats, "SummaryCategories"
    )
    if not category.empty and "net_revenue" in category:
        add_column_chart(
            workbook,
            worksheet,
            sheet_name="01_Executive_Summary",
            first_data_row=category_start + 1,
            last_data_row=category_start + len(category),
            category_column=0,
            value_column=list(category.columns).index("net_revenue"),
            title="Revenue by Category",
            position="J31",
            currency_axis=context.default_currency,
            theme=context.formats.theme,
        )
    row = max(row, 48)

    targets = _target_achievement(context)
    write_section_header(worksheet, row, "Targets vs Actual", context.formats)
    target_start = row + 1
    row = write_dataframe_table(
        worksheet,
        targets,
        target_start,
        0,
        context.formats,
        "SummaryTargets",
        empty_message="No monthly target data is available.",
    )
    if not targets.empty and "target_achievement" in targets:
        column = list(targets.columns).index("target_achievement")
        first, last = target_start + 1, target_start + len(targets)
        worksheet.conditional_format(
            first,
            column,
            last,
            column,
            {
                "type": "cell",
                "criteria": ">=",
                "value": context.visual_thresholds.exceeded_target_ratio,
                "format": context.formats.success,
                "stop_if_true": True,
            },
        )
        worksheet.conditional_format(
            first,
            column,
            last,
            column,
            {
                "type": "cell",
                "criteria": "between",
                "minimum": 1,
                "maximum": context.visual_thresholds.exceeded_target_ratio,
                "format": context.formats.success,
                "stop_if_true": True,
            },
        )
        worksheet.conditional_format(
            first,
            column,
            last,
            column,
            {
                "type": "cell",
                "criteria": "between",
                "minimum": context.visual_thresholds.close_to_target_ratio,
                "maximum": 1,
                "format": context.formats.warning,
                "stop_if_true": True,
            },
        )
        worksheet.conditional_format(
            first,
            column,
            last,
            column,
            {
                "type": "cell",
                "criteria": "<",
                "value": context.visual_thresholds.close_to_target_ratio,
                "format": context.formats.error,
            },
        )

    priority = context.recommendations.loc[
        context.recommendations.get("severity", pd.Series(dtype=str)).isin(["critical", "warning"])
    ].head(8)
    write_section_header(worksheet, row, "Critical Alerts", context.formats)
    row = write_dataframe_table(
        worksheet,
        priority,
        row + 1,
        0,
        context.formats,
        "SummaryAlerts",
        empty_message="No critical or warning alerts were generated.",
    )
    if "04_Inventory" in context.included_worksheets:
        write_internal_link(
            worksheet,
            f"J{row - 1}",
            "04_Inventory",
            "View Inventory Detail",
            context.formats,
        )

    write_section_header(worksheet, row, "Top Products", context.formats)
    row = write_dataframe_table(
        worksheet,
        context.sales.top_products_by_revenue.head(10),
        row + 1,
        0,
        context.formats,
        "SummaryTopProducts",
    )
    write_internal_link(
        worksheet, f"J{row - 1}", "03_Product_Performance", "View Product Detail", context.formats
    )

    write_section_header(worksheet, row, "Priority Recommendations", context.formats)
    row = write_dataframe_table(
        worksheet,
        context.recommendations.head(10),
        row + 1,
        0,
        context.formats,
        "SummaryRecommendations",
        empty_message="No recommendations were generated for this period.",
    )
    configure_print_layout(
        worksheet,
        report_id=context.report_id,
        generated_at=context.generated_at,
        last_row=row,
        last_column=15,
    )
    return row
