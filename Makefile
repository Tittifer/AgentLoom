.PHONY: dev dev-stop check

dev:
	uv run --locked python scripts/dev.py

dev-stop:
	docker compose stop postgres

check:
	uv run --locked ruff format --check .
	uv run --locked ruff check .
	uv run --locked pyright
	uv run --locked pytest
	npm --prefix frontend run typecheck
	npm --prefix frontend run build
