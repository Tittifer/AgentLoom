.PHONY: dev dev-docker dev-stop test test-frontend e2e check release-check

dev:
	uv run --locked python scripts/dev.py

dev-docker:
	uv run --locked python scripts/dev.py --with-docker

dev-stop:
	docker compose stop postgres

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
	uv run --locked alembic upgrade head
	npm --prefix frontend ci
	npm --prefix frontend run lint
	npm --prefix frontend run typecheck
	npm --prefix frontend run test
	npm --prefix frontend run build
