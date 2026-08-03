"""Generate reproducible synthetic datasets for RetailFlow Analytics."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
import typer

DEFAULT_ORDER_COUNT = 5_000
DEFAULT_PRODUCT_COUNT = 200
DEFAULT_SEED = 42

COUNTRIES = ("Cyprus", "France", "Germany", "Ireland", "Italy", "Netherlands", "Spain")
COUNTRY_CURRENCIES = {
    "Cyprus": "EUR",
    "France": "EUR",
    "Germany": "EUR",
    "Ireland": "EUR",
    "Italy": "EUR",
    "Netherlands": "EUR",
    "Spain": "EUR",
}
CATEGORIES = ("Electronics", "Home", "Office", "Outdoor", "Sports", "Wellness")
SUPPLIERS = (
    "Alpine Supply Co.",
    "Baltic Wholesale",
    "Continental Goods",
    "Meridian Imports",
    "Nordic Trade Partners",
)
WAREHOUSES = ("Amsterdam", "Berlin", "Dublin", "Nicosia")
SALES_CHANNELS = ("Website", "Amazon", "Marketplace", "Wholesale")
ORDER_STATUSES = ("completed", "cancelled", "pending")
RETURN_REASONS = (
    "Damaged in transit",
    "Defective product",
    "Incorrect item",
    "No longer required",
    "Size or fit issue",
)


@dataclass(frozen=True)
class GenerationSummary:
    """Aggregate counts from a demonstration-data generation run."""

    output_directory: Path
    orders: int
    products: int
    inventory_rows: int
    returns: int
    targets: int
    invalid_rows_included: bool


def _validate_generation_options(
    number_of_orders: int,
    number_of_products: int,
    include_invalid_rows: bool,
) -> None:
    """Validate options before creating any output files."""
    if number_of_orders <= 0:
        raise ValueError("The number of orders must be greater than zero.")
    if number_of_products <= 0:
        raise ValueError("The number of products must be greater than zero.")
    if include_invalid_rows and number_of_orders < 6:
        raise ValueError(
            "At least 6 orders are required when invalid demonstration rows are enabled."
        )
    if include_invalid_rows and number_of_products < 2:
        raise ValueError(
            "At least 2 products are required when invalid demonstration rows are enabled."
        )


def _generate_products(
    random_source: random.Random,
    number_of_products: int,
    include_invalid_rows: bool,
) -> pd.DataFrame:
    """Create a product catalogue with varied categories and suppliers."""
    descriptors = ("Classic", "Compact", "Essential", "Premium", "Smart", "Travel")
    nouns = ("Bundle", "Device", "Kit", "Pack", "Set", "Solution")
    records: list[dict[str, Any]] = []
    vat_rates = (0.05, 0.09, 0.19, 0.20, 0.21)

    for index in range(number_of_products):
        purchase_cost = round(random_source.uniform(4.0, 350.0), 2)
        recommended_price = round(purchase_cost * random_source.uniform(1.25, 2.4), 2)
        records.append(
            {
                "product_id": f"P{index + 1:05d}",
                "product_name": (
                    f"{descriptors[index % len(descriptors)]} "
                    f"{nouns[(index // len(descriptors)) % len(nouns)]} {index + 1}"
                ),
                "category": CATEGORIES[index % len(CATEGORIES)],
                "supplier": SUPPLIERS[index % len(SUPPLIERS)],
                "purchase_cost": purchase_cost,
                "recommended_price": recommended_price,
                "vat_rate": random_source.choice(vat_rates),
            }
        )

    products = pd.DataFrame.from_records(records)
    if include_invalid_rows:
        products.loc[products.index[-1], "product_name"] = None
    return products


def _active_product_ids(products: pd.DataFrame) -> list[str]:
    """Reserve a small catalogue segment as products with no recent sales."""
    all_ids = products["product_id"].astype(str).tolist()
    if len(all_ids) == 1:
        return all_ids
    inactive_count = max(1, len(all_ids) // 20)
    return all_ids[:-inactive_count]


def _generate_orders(
    random_source: random.Random,
    products: pd.DataFrame,
    number_of_orders: int,
    include_invalid_rows: bool,
) -> pd.DataFrame:
    """Create synthetic orders across European markets and sales channels."""
    active_products = _active_product_ids(products)
    product_prices = products.set_index("product_id")["recommended_price"].to_dict()
    start_date = date(2025, 1, 1)
    customer_count = max(50, number_of_orders // 4)
    records: list[dict[str, Any]] = []

    for index in range(number_of_orders):
        product_id = random_source.choice(active_products)
        country = COUNTRIES[index % len(COUNTRIES)]
        status = (
            ORDER_STATUSES[index]
            if index < len(ORDER_STATUSES)
            else random_source.choices(ORDER_STATUSES, weights=(82, 8, 10), k=1)[0]
        )
        base_price = float(product_prices[product_id])
        records.append(
            {
                "order_id": f"O{index + 1:07d}",
                "order_date": (
                    start_date + timedelta(days=random_source.randrange(365))
                ).isoformat(),
                "customer_id": f"C{random_source.randint(1, customer_count):06d}",
                "product_id": product_id,
                "quantity": random_source.choices((1, 2, 3, 4, 5), weights=(55, 25, 12, 5, 3))[0],
                "unit_price": round(base_price * random_source.uniform(0.95, 1.05), 2),
                "discount": random_source.choices(
                    (0.0, 0.05, 0.10, 0.15, 0.20), weights=(55, 12, 20, 8, 5)
                )[0],
                "currency": COUNTRY_CURRENCIES[country],
                "country": country,
                "sales_channel": SALES_CHANNELS[index % len(SALES_CHANNELS)],
                "order_status": status,
            }
        )

    orders = pd.DataFrame.from_records(records)
    if include_invalid_rows:
        duplicate = orders.iloc[[0]].copy()
        orders.loc[1, "product_id"] = "P_UNKNOWN"
        orders.loc[2, "quantity"] = -2
        orders.loc[3, "order_date"] = None
        orders.loc[4, "currency"] = "XYZ"
        orders["unit_price"] = orders["unit_price"].astype(object)
        invalid_price = str(orders.at[5, "unit_price"])
        orders.loc[5, "unit_price"] = f"{invalid_price} EUR"
        orders = pd.concat([orders, duplicate], ignore_index=True)
    return orders


def _generate_inventory(
    random_source: random.Random,
    products: pd.DataFrame,
    include_invalid_rows: bool,
) -> pd.DataFrame:
    """Create multi-warehouse inventory with shortage and overstock scenarios."""
    records: list[dict[str, Any]] = []
    reference_date = date(2025, 12, 31)

    for product_id in products["product_id"].astype(str):
        warehouse_count = random_source.randint(1, min(3, len(WAREHOUSES)))
        for warehouse in random_source.sample(WAREHOUSES, warehouse_count):
            stock_quantity = random_source.randint(0, 300)
            records.append(
                {
                    "product_id": product_id,
                    "warehouse": warehouse,
                    "stock_quantity": stock_quantity,
                    "reserved_quantity": random_source.randint(0, stock_quantity),
                    "reorder_level": random_source.randint(10, 60),
                    "last_restock_date": (
                        reference_date - timedelta(days=random_source.randint(1, 300))
                    ).isoformat(),
                }
            )

    inventory = pd.DataFrame.from_records(records)
    inventory.loc[0, ["stock_quantity", "reserved_quantity", "reorder_level"]] = [2, 1, 25]
    inventory.loc[1, ["stock_quantity", "reserved_quantity", "reorder_level"]] = [800, 5, 40]
    if include_invalid_rows:
        inventory.loc[0, "reserved_quantity"] = 4
    return inventory


def _generate_returns(
    random_source: random.Random,
    orders: pd.DataFrame,
    include_invalid_rows: bool,
) -> pd.DataFrame:
    """Create returns for a subset of completed, otherwise valid orders."""
    eligible_orders = orders[
        (orders["order_status"] == "completed")
        & (orders["quantity"] > 0)
        & (orders["product_id"] != "P_UNKNOWN")
        & orders["order_date"].notna()
    ].drop_duplicates(subset="order_id")
    return_count = min(len(eligible_orders), max(1, round(len(eligible_orders) * 0.06)))
    sampled_indices = random_source.sample(eligible_orders.index.tolist(), return_count)
    records: list[dict[str, Any]] = []

    for index, order_index in enumerate(sampled_indices, start=1):
        order = eligible_orders.loc[order_index]
        returned_quantity = random_source.randint(1, int(order["quantity"]))
        order_date = date.fromisoformat(str(order["order_date"]))
        unit_price = float(order["unit_price"])
        records.append(
            {
                "return_id": f"R{index:06d}",
                "order_id": str(order["order_id"]),
                "product_id": str(order["product_id"]),
                "return_date": (
                    order_date + timedelta(days=random_source.randint(1, 30))
                ).isoformat(),
                "quantity": returned_quantity,
                "return_reason": random_source.choice(RETURN_REASONS),
                "refund_amount": round(
                    returned_quantity * unit_price * (1 - float(order["discount"])), 2
                ),
            }
        )

    if include_invalid_rows:
        records.append(
            {
                "return_id": f"R{len(records) + 1:06d}",
                "order_id": "O_MISSING",
                "product_id": str(orders.iloc[0]["product_id"]),
                "return_date": "2025-12-31",
                "quantity": 1,
                "return_reason": "Incorrect item",
                "refund_amount": 25.0,
            }
        )
    return pd.DataFrame.from_records(records)


def _generate_targets(random_source: random.Random) -> pd.DataFrame:
    """Create monthly revenue, profit, and order targets for one calendar year."""
    records: list[dict[str, Any]] = []
    for month_number in range(1, 13):
        revenue_target = round(random_source.uniform(180_000, 320_000), 2)
        records.append(
            {
                "month": f"2025-{month_number:02d}",
                "revenue_target": revenue_target,
                "profit_target": round(revenue_target * random_source.uniform(0.18, 0.28), 2),
                "orders_target": random_source.randint(350, 600),
            }
        )
    return pd.DataFrame.from_records(records)


def generate_demo_data(
    output_directory: str | Path = Path("demo_data"),
    number_of_orders: int = DEFAULT_ORDER_COUNT,
    number_of_products: int = DEFAULT_PRODUCT_COUNT,
    random_seed: int = DEFAULT_SEED,
    include_invalid_rows: bool = True,
) -> GenerationSummary:
    """Generate all demonstration datasets and return aggregate row counts."""
    _validate_generation_options(number_of_orders, number_of_products, include_invalid_rows)
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    random_source = random.Random(random_seed)

    products = _generate_products(random_source, number_of_products, include_invalid_rows)
    orders = _generate_orders(random_source, products, number_of_orders, include_invalid_rows)
    inventory = _generate_inventory(random_source, products, include_invalid_rows)
    returns = _generate_returns(random_source, orders, include_invalid_rows)
    targets = _generate_targets(random_source)

    orders.to_csv(destination / "orders.csv", index=False)
    products.to_excel(destination / "products.xlsx", index=False, sheet_name="products")
    inventory.to_csv(destination / "inventory.csv", index=False)
    returns.to_excel(destination / "returns.xlsx", index=False, sheet_name="returns")
    targets.to_csv(destination / "monthly_targets.csv", index=False)

    return GenerationSummary(
        output_directory=destination,
        orders=len(orders),
        products=len(products),
        inventory_rows=len(inventory),
        returns=len(returns),
        targets=len(targets),
        invalid_rows_included=include_invalid_rows,
    )


def main(
    output_directory: Annotated[
        Path,
        typer.Option("--output-directory", "--output-dir", help="Directory for generated files."),
    ] = Path("demo_data"),
    number_of_orders: Annotated[
        int,
        typer.Option("--number-of-orders", "--num-orders", min=1, help="Base order count."),
    ] = DEFAULT_ORDER_COUNT,
    number_of_products: Annotated[
        int,
        typer.Option("--number-of-products", "--num-products", min=1, help="Product count."),
    ] = DEFAULT_PRODUCT_COUNT,
    random_seed: Annotated[
        int,
        typer.Option("--random-seed", "--seed", help="Seed for reproducible generation."),
    ] = DEFAULT_SEED,
    include_invalid_rows: Annotated[
        bool,
        typer.Option(
            "--include-invalid-rows/--exclude-invalid-rows",
            help="Include controlled data-quality problems.",
        ),
    ] = True,
) -> None:
    """Generate synthetic RetailFlow business data from the command line."""
    try:
        summary = generate_demo_data(
            output_directory=output_directory,
            number_of_orders=number_of_orders,
            number_of_products=number_of_products,
            random_seed=random_seed,
            include_invalid_rows=include_invalid_rows,
        )
    except (OSError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error

    typer.echo(
        "Generated "
        f"{summary.orders:,} orders, {summary.products:,} products, "
        f"{summary.inventory_rows:,} inventory rows, {summary.returns:,} returns, "
        f"and {summary.targets:,} monthly targets in '{summary.output_directory}'."
    )
    typer.echo(f"Invalid demonstration rows included: {summary.invalid_rows_included}.")


if __name__ == "__main__":
    typer.run(main)
