.PHONY: dev test test-frontend e2e check release-check

dev:
	uv run --locked python dev.py

test:
	uv run --locked pytest --cov=agentloom --cov-report=term-missing

test-frontend:
	npm --prefix frontend run test

e2e:
	npm --prefix frontend run test:e2e

check:
	uv run --locked ruff format --check .
	uv run --locked ruff check .
	uv run --locked pyright
	uv run --locked pytest --cov=agentloom --cov-report=term-missing
	npm --prefix frontend run lint
	npm --prefix frontend run typecheck
	npm --prefix frontend run test
	npm --prefix frontend run build

release-check:
	uv lock --check
	uv run --locked ruff format --check .
	uv run --locked ruff check .
	uv run --locked pyright
	uv run --locked pytest -m "not live" --cov=agentloom --cov-report=term-missing
	npm --prefix frontend ci
	npm --prefix frontend run lint
	npm --prefix frontend run typecheck
	npm --prefix frontend run test
	npm --prefix frontend run build
