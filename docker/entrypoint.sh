#!/bin/sh
set -eu

if [ "${RETAILFLOW_GENERATE_DEMO_DATA:-false}" = "true" ] \
    && [ ! -f /app/demo_data/orders.csv ]; then
    python -m retailflow generate-demo-data \
        --output-directory /app/demo_data \
        --number-of-orders "${RETAILFLOW_DEMO_ORDER_COUNT:-5000}" \
        --number-of-products "${RETAILFLOW_DEMO_PRODUCT_COUNT:-200}" \
        --random-seed "${RETAILFLOW_DEMO_RANDOM_SEED:-42}"
fi

exec "$@"
