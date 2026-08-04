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
