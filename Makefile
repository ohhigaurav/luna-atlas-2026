SHELL := /bin/bash
.PHONY: setup run run-offline test verify lint typecheck api validate-catalogue fetch-kernels bootstrap-data

setup:
	uv sync

run:
	./scripts/run_local.sh

run-offline:
	./scripts/run_local.sh --offline

test:
	uv run pytest -q

verify:
	./scripts/verify_project.sh

lint:
	uv run ruff check backend tests tools

typecheck:
	uv run mypy backend/lunar_core

api:
	uv run uvicorn lunar_core.api:app --app-dir backend --reload

validate-catalogue:
	uv run python -m lunar_core.cli validate-catalogue

fetch-kernels:
	uv run python tools/fetch_kernels.py

bootstrap-data:
	./scripts/bootstrap_public_reference.sh
