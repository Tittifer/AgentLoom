# AgentLoom

AgentLoom is a lightweight multi-agent collaboration project. The repository root is
the FastAPI backend project, while `frontend/` is a separate React package.

## Prerequisites

- Python 3.11 managed by uv
- Node.js 22 and npm 10
- Docker Engine with Docker Compose v2
- GNU Make

## Repository layout

```text
src/       FastAPI backend package
tests/     Backend tests
frontend/  Independent React and TypeScript package
examples/  Example task and workflow inputs
tmp/       Local planning documents (not committed)
```

## Run the development environment

Start PostgreSQL, FastAPI with reload, and Vite from the repository root:

```bash
make dev
```

The command installs frontend dependencies with `npm ci` when they are missing.
Press `Ctrl+C` to stop FastAPI and Vite. PostgreSQL remains available so its
persistent development data is preserved; stop it separately with:

```bash
make dev-stop
```

If GNU Make is unavailable, the equivalent command is:

```bash
uv run --locked python scripts/dev.py
```

## Run the backend

```bash
uv sync
uv run uvicorn agentloom.main:app --reload
```

The health endpoint is available at <http://localhost:8000/health>.

## Run PostgreSQL

Copy the development environment template if you do not already have a local
`.env` file, then start PostgreSQL:

```bash
cp .env.example .env
docker compose up -d postgres
docker compose ps
```

The database is exposed on `localhost:15432` by default, avoiding conflicts
with locally installed PostgreSQL instances. Its data is stored in
the `postgres_data` named volume and survives ordinary container recreation.
The values in `.env.example` are development defaults and must not be used as
production credentials.

To stop the database without deleting its data:

```bash
docker compose stop postgres
```

## Manage database migrations

Apply all committed migrations after PostgreSQL is healthy:

```bash
uv run --locked alembic upgrade head
uv run --locked alembic current
```

After changing ORM models, generate and inspect a migration before applying it:

```bash
uv run --locked alembic revision --autogenerate -m "describe schema change"
uv run --locked alembic upgrade head
uv run --locked alembic check
```

Revert the latest migration during development with:

```bash
uv run --locked alembic downgrade -1
```

## Run backend checks

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

## Run the frontend

```bash
cd frontend
npm ci
npm run dev
```

The task list is available at <http://localhost:5173/tasks>. The page checks
the backend health endpoint through the Vite development proxy.

