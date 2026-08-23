.PHONY: dev dev-docker dev-stop test check

dev:
	uv run --locked python scripts/dev.py

dev-docker:
	uv run --locked python scripts/dev.py --with-docker

dev-stop:
	docker compose stop postgres

test:
	uv run --locked pytest --cov=agentloom --cov-report=term-missing

check:
	uv run --locked ruff format --check .
	uv run --locked ruff check .
	uv run --locked pyright
	uv run --locked pytest --cov=agentloom --cov-report=term-missing
	npm --prefix frontend run typecheck
	npm --prefix frontend run build
