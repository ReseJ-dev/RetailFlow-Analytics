.PHONY: install test lint format typecheck type-check check run demo-data \
	docker-build docker-up docker-down docker-logs

COMPOSE ?= docker compose

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	python -m ruff check .

format:
	python -m ruff format .

typecheck:
	python -m mypy src app

type-check: typecheck

check: lint typecheck test

run:
	python -m streamlit run app/main.py

demo-data:
	python -m retailflow generate-demo-data --output-directory demo_data

docker-build:
	$(COMPOSE) build retailflow

docker-up:
	$(COMPOSE) up --build -d

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs --follow retailflow
