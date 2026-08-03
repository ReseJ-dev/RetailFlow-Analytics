"""Returns KPIs, reason analysis, and product return-rate rankings."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from retailflow.analytics.models import (
    AnalyticsFilters,
    ReturnsAnalyticsResult,
    ReturnsKPIs,
)
from retailflow.analytics.sales_metrics import (
    _filter_returns_date,
    as_decimal,
    prepare_sales_data,
    round_money,
    safe_percentage,
)


def prepare_returns_data(
    orders: pd.DataFrame,
    returns: pd.DataFrame,
    filters: AnalyticsFilters | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Filter returns through matching completed order lines and return dates."""
    sold = prepare_sales_data(orders, None, filters)
    filtered = _filter_returns_date(returns, filters)
    if filtered.empty or sold.empty:
        return filtered.iloc[0:0].copy(), sold

    sold_keys = set(zip(sold["order_id"].astype(str), sold["product_id"].astype(str), strict=True))
    mask = [
        (str(row["order_id"]), str(row["product_id"])) in sold_keys
        for _, row in filtered.iterrows()
    ]
    filtered = filtered.loc[mask].copy().reset_index(drop=True)
    if filtered.empty:
        return filtered, sold

    attributes = [
        column
        for column in (
            "order_id",
            "product_id",
            "product_name",
            "category",
            "country",
            "sales_channel",
            "currency",
            "order_status",
        )
        if column in sold
    ]
    lookup = sold[attributes].drop_duplicates(["order_id", "product_id"])
    existing_attributes = set(filtered.columns) - {"order_id", "product_id"}
    lookup = lookup.drop(
        columns=[column for column in lookup if column in existing_attributes],
        errors="ignore",
    )
    if set(lookup.columns) - {"order_id", "product_id"}:
        filtered = filtered.merge(
            lookup,
            on=["order_id", "product_id"],
            how="left",
            validate="many_to_one",
        )
    filtered["returned_quantity"] = [int(as_decimal(value)) for value in filtered["quantity"]]
    filtered["refund_amount"] = pd.Series(
        [as_decimal(value) for value in filtered["refund_amount"]], dtype=object
    )
    return filtered, sold


def calculate_returns_kpis(
    enriched_returns: pd.DataFrame, sold_orders: pd.DataFrame
) -> ReturnsKPIs:
    returned = (
        int(enriched_returns["returned_quantity"].sum())
        if "returned_quantity" in enriched_returns
        else 0
    )
    refund = (
        sum(enriched_returns["refund_amount"], Decimal("0"))
        if "refund_amount" in enriched_returns
        else Decimal("0")
    )
    sold = int(sold_orders["quantity"].sum()) if "quantity" in sold_orders else 0
    return ReturnsKPIs(
        returned_quantity=returned,
        refund_amount=round_money(refund),
        return_rate_percent=safe_percentage(Decimal(returned), Decimal(sold)),
    )


def return_reasons(enriched_returns: pd.DataFrame) -> pd.DataFrame:
    columns = ("return_reason", "returns", "returned_quantity", "refund_amount")
    if enriched_returns.empty or "return_reason" not in enriched_returns:
        return pd.DataFrame(columns=columns)
    records: list[dict[str, object]] = []
    for reason, group in enriched_returns.groupby("return_reason", dropna=False, sort=True):
        records.append(
            {
                "return_reason": reason,
                "returns": (
                    int(group["return_id"].nunique()) if "return_id" in group else len(group)
                ),
                "returned_quantity": int(group["returned_quantity"].sum()),
                "refund_amount": round_money(sum(group["refund_amount"], Decimal("0"))),
            }
        )
    return (
        pd.DataFrame.from_records(records, columns=columns)
        .sort_values(["returned_quantity", "return_reason"], ascending=[False, True])
        .reset_index(drop=True)
    )


def products_by_return_rate(
    enriched_returns: pd.DataFrame, sold_orders: pd.DataFrame, limit: int = 10
) -> pd.DataFrame:
    columns = (
        "product_id",
        "product_name",
        "units_sold",
        "returned_quantity",
        "refund_amount",
        "return_rate",
        "return_rate_percent",
    )
    if sold_orders.empty:
        return pd.DataFrame(columns=columns)
    records: list[dict[str, object]] = []
    for product_id, sold_group in sold_orders.groupby("product_id", sort=True):
        returned_group = (
            enriched_returns.loc[enriched_returns["product_id"].astype(str) == str(product_id)]
            if "product_id" in enriched_returns
            else enriched_returns.iloc[0:0]
        )
        units_sold = int(sold_group["quantity"].sum())
        returned = (
            int(returned_group["returned_quantity"].sum())
            if "returned_quantity" in returned_group
            else 0
        )
        refund = (
            sum(returned_group["refund_amount"], Decimal("0"))
            if "refund_amount" in returned_group
            else Decimal("0")
        )
        product_name = sold_group["product_name"].iloc[0] if "product_name" in sold_group else pd.NA
        records.append(
            {
                "product_id": product_id,
                "product_name": product_name,
                "units_sold": units_sold,
                "returned_quantity": returned,
                "refund_amount": round_money(refund),
                "return_rate": safe_percentage(Decimal(returned), Decimal(units_sold)),
                "return_rate_percent": safe_percentage(Decimal(returned), Decimal(units_sold)),
            }
        )
    return (
        pd.DataFrame.from_records(records, columns=columns)
        .sort_values(
            ["return_rate_percent", "returned_quantity", "product_id"],
            ascending=[False, False, True],
        )
        .head(limit)
        .reset_index(drop=True)
    )


def calculate_returns_metrics(
    orders: pd.DataFrame,
    returns: pd.DataFrame,
    filters: AnalyticsFilters | None = None,
) -> ReturnsKPIs:
    enriched_returns, sold_orders = prepare_returns_data(orders, returns, filters)
    return calculate_returns_kpis(enriched_returns, sold_orders)


def calculate_returns_analytics(
    orders: pd.DataFrame,
    returns: pd.DataFrame,
    filters: AnalyticsFilters | None = None,
    *,
    top_n: int = 10,
) -> ReturnsAnalyticsResult:
    enriched_returns, sold_orders = prepare_returns_data(orders, returns, filters)
    return ReturnsAnalyticsResult(
        kpis=calculate_returns_kpis(enriched_returns, sold_orders),
        enriched_returns=enriched_returns,
        return_reasons=return_reasons(enriched_returns),
        products_by_return_rate=products_by_return_rate(enriched_returns, sold_orders, top_n),
    )


calculate_return_reasons = return_reasons
calculate_products_by_return_rate = products_by_return_rate
