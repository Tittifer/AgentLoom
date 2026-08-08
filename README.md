# AgentLoom

AgentLoom is a lightweight multi-agent collaboration project. The repository is organized as a separated React frontend and FastAPI backend; PostgreSQL persistence is introduced in the next implementation step.

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

