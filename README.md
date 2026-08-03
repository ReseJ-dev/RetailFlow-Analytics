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

To start the placeholder Streamlit application:

```bash
make run
```
