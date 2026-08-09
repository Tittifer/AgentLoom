# AgentLoom

AgentLoom is a lightweight multi-agent collaboration project. The repository is organized as a separated React frontend and FastAPI backend with PostgreSQL persistence.

## Prerequisites

- Python 3.11 managed by uv
- Node.js 22 and npm 10
- Docker Engine with Docker Compose v2

## Repository layout

```text
frontend/  React and TypeScript application
backend/   FastAPI application
examples/  Example task and workflow inputs
tmp/       Local planning documents (not committed)
```

## Run the backend

```bash
cd backend
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

The database is exposed on `localhost:5432` by default. Its data is stored in
the `postgres_data` named volume and survives ordinary container recreation.
The values in `.env.example` are development defaults and must not be used as
production credentials.

To stop the database without deleting its data:

```bash
docker compose stop postgres
```

## Run backend checks

```bash
cd backend
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

## Run the frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend is available at <http://localhost:5173>.

