.PHONY: install test lint format type-check check run

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	python -m ruff check .

format:
	python -m ruff format .

type-check:
	python -m mypy src app

check: lint type-check test

run:
	python -m streamlit run app/main.py
