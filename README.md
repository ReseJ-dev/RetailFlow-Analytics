# RetailFlow Analytics

RetailFlow Analytics is a production-oriented Python application for validating, cleaning, combining, and analysing sales, product, inventory, returns, and sales-target data, with Excel management reporting and a Streamlit interface planned for later development.

> **Development status:** Initial project scaffold. Business features are not yet implemented.

## Local setup

Python 3.12 is required.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
make check
```

## Command-line interface

Run the CLI with `python -m retailflow --help`. For example:

```bash
python -m retailflow validate --config config/config.example.yaml
python -m retailflow generate --config config/config.example.yaml --period 2025-01
python -m retailflow generate-demo-data --output-directory demo_data
```

Stable exit codes are: `0` success, `2` configuration error, `3` source-file
error, `4` validation failure, `5` report-generation failure, and `10`
unexpected internal error. Tracebacks are hidden by default and enabled with
`--debug` on commands that perform file or configuration work.

To start the placeholder Streamlit application:

```bash
make run
```

## Demonstration REST API

The local mock source uses bearer authentication and serves paginated orders,
products, inventory, and returns. Copy `.env.example` to `.env` for the documented
local-only demo token, export the two variables, and start the ASGI server:

```bash
set -a
source .env
set +a
uvicorn mock_api.main:app --reload
```

Open Upload Data in Streamlit to test the connection or load the API datasets.
For CLI API mode, use a YAML file with `sources.mode: api` and `sources.api_url`
set, then run `python -m retailflow validate --config config/api.yaml`. The token
must come from `RETAIL_API_TOKEN`; it is never written to YAML, SQLite, or logs.
File and API sources cannot be combined unless `sources.allow_mixed_sources` is
explicitly enabled.
