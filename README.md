# AgentLoom

AgentLoom is a lightweight, database-backed multi-agent workflow application. A Planner turns a natural-language task into a validated DAG; asynchronous Workers execute ready nodes, a deterministic Reviewer validates structured results, and the React UI streams persisted progress over SSE.

## Current scope

Version `0.1.0` is intentionally limited to:

- one backend process and one scheduler;
- one trusted user with no authentication or authorization;
- read-only registered tools;
- PostgreSQL persistence;
- a deterministic offline MockLLM or a LiteLLM-backed provider;
- at most 20 nodes per workflow and configurable bounded concurrency/retries.

Do not expose this version directly to untrusted networks. Multi-user isolation, distributed scheduling, write-capable tools, quotas, and production authentication are outside the MVP.

## Repository layout

```text
src/                  FastAPI backend package
tests/                Backend unit, integration, contract, and E2E support
frontend/             React, TypeScript, Vitest, and Playwright package
alembic/              PostgreSQL migrations
examples/             Product-research workflow example
scripts/              Local development launcher
compose.yaml          Optional development PostgreSQL service
```

## Prerequisites

- Python 3.11
- [uv](https://docs.astral.sh/uv/)
- Node.js 22 and npm 10
- PostgreSQL 16, installed locally or started by the optional development Compose service
- GNU Make is optional; PowerShell users can run the equivalent commands directly

## Local development

Copy the example configuration and install dependencies:

```powershell
Copy-Item .env.example .env
uv sync --locked --all-groups
npm --prefix frontend ci
```

If PostgreSQL is installed locally, create the configured database and apply migrations:

```powershell
uv run --locked alembic upgrade head
```

Start the backend and frontend together:

```powershell
uv run --locked python scripts/dev.py
```

Alternatively, start the development PostgreSQL container first:

```powershell
uv run --locked python scripts/dev.py --with-docker
```

On systems with GNU Make, the equivalent commands are `make dev` and `make dev-docker`. Open <http://localhost:5173/tasks>; FastAPI health is available at <http://localhost:8000/health>.

## Model configuration

The default configuration is completely offline:

```dotenv
AGENTLOOM_LLM_PROVIDER=mock
AGENTLOOM_LLM_MODEL=mock/schema
AGENTLOOM_LLM_RESPONSE_FORMAT=json_schema
```

For a model supported by LiteLLM, set:

```dotenv
AGENTLOOM_LLM_PROVIDER=litellm
AGENTLOOM_LLM_MODEL=openai/gpt-4.1-mini
AGENTLOOM_LLM_RESPONSE_FORMAT=json_schema
OPENAI_API_KEY=replace-with-your-key
```

For an OpenAI-compatible endpoint that supports JSON objects but rejects strict JSON Schema, use:

```dotenv
AGENTLOOM_LLM_PROVIDER=litellm
AGENTLOOM_LLM_MODEL=openai/provider-model-id
AGENTLOOM_LLM_RESPONSE_FORMAT=json_object
OPENAI_BASE_URL=https://provider.example/v1
OPENAI_API_KEY=replace-with-your-key
```

`json_schema` remains the default and provides provider-side strict validation. The `json_object` compatibility mode relies on AgentLoom's local Pydantic, DAG, and Reviewer validation. Use the provider-specific environment variables required by LiteLLM. Never commit `.env` or API keys. `AGENTLOOM_LLM_TIMEOUT_SECONDS` bounds each model call and `AGENTLOOM_WORKER_MAX_TURNS` bounds each Worker tool loop.

## Run tests and checks

Backend tests use PostgreSQL but never require a model API key:

```powershell
uv run --locked pytest -m "not live" --cov=agentloom --cov-report=term-missing
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
```

Frontend checks are also offline:

```powershell
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
```

Install Chromium once and run the full product-research browser flow:

```powershell
Set-Location frontend
npx playwright install chromium
npm run test:e2e
Set-Location ..
```

The E2E test starts isolated FastAPI and Vite processes, uses a deterministic MockLLM, exercises one Reviewer retry, and needs the configured PostgreSQL database.

## Database migrations

Apply and inspect migrations from the repository root:

```powershell
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
```

Apply committed migrations before starting Uvicorn. Run only one backend instance during `0.1.0`; recovery and scheduling use a single-process ownership model.

## Runtime behavior

- Startup recovery finds queued/running Runs, keeps completed nodes, resets interrupted running/reviewing attempts, records `run.recovered`, and resumes scheduling.
- Cancelling a Run marks all unfinished attempts cancelled. A model call already in flight may finish, but its output cannot transition or commit.
- Retrying a failed Run creates a new Run using the same immutable Workflow and input. The failed Run remains available as history.
- SSE events are persisted before notification, support replay, and close in the UI when a Run completes, fails, or is cancelled.

## Release check

Run the complete local release gate:

```powershell
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
npm --prefix frontend run test:e2e
```

The repository includes a GitHub Actions workflow that runs the same offline backend, frontend, migration, and Playwright checks against PostgreSQL 16.
