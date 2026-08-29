# AgentLoom

AgentLoom 是一个轻量级、由数据库提供持久化支持的多智能体工作流应用。规划器（Planner）将自然语言任务转换为经过校验的 DAG；异步工作器（Worker）执行已就绪的节点，确定性审核器（Reviewer）校验结构化结果，React 界面通过 SSE 实时展示已持久化的执行进度。

## 当前范围

版本 `0.1.0` 有意限定为：

- 单个后端进程和单个调度器；
- 单个可信用户，不包含身份认证或权限控制；
- 仅支持已注册的只读工具；
- 使用 PostgreSQL 持久化数据；
- 使用确定性的离线 MockLLM，或由 LiteLLM 支持的模型提供商；
- 每个工作流最多包含 20 个节点，并支持配置有界的并发数和重试次数。

请勿将此版本直接暴露在不可信网络中。多用户隔离、分布式调度、可写工具、配额以及生产环境身份认证均不在 MVP 范围内。

## 仓库结构

```text
agentloom/            FastAPI 后端包
tests/agentloom/      与后端源码路径对应的单元测试
tests/integration/    后端集成测试
tests/contract/       模型提供商契约测试
frontend/             React、TypeScript、Vitest 和 Playwright 前端包
alembic/              PostgreSQL 数据库迁移
examples/             产品研究工作流示例
scripts/              本地开发启动脚本
compose.yaml          可选的开发用 PostgreSQL 服务
```

## 环境要求

- Python 3.11
- [uv](https://docs.astral.sh/uv/)
- Node.js 22 和 npm 10
- PostgreSQL 16：可以安装在本机，也可以通过可选的开发用 Compose 服务启动
- GNU Make 为可选工具；PowerShell 用户可以直接运行对应命令

## 本地开发

复制示例配置并安装依赖：

```powershell
Copy-Item .env.example .env
uv sync --locked --all-groups
npm --prefix frontend ci
```

如果 PostgreSQL 安装在本机，请先创建配置中指定的数据库，然后执行迁移：

```powershell
uv run --locked alembic upgrade head
```

同时启动后端和前端：

```powershell
uv run --locked python scripts/dev.py
```

也可以先启动开发用 PostgreSQL 容器：

```powershell
uv run --locked python scripts/dev.py --with-docker
```

在安装了 GNU Make 的系统中，对应命令为 `make dev` 和 `make dev-docker`。启动后访问 <http://localhost:5173/tasks>；FastAPI 健康检查地址为 <http://localhost:8000/health>。

## 模型配置

默认配置完全离线运行：

```dotenv
AGENTLOOM_LLM_PROVIDER=mock
AGENTLOOM_LLM_MODEL=mock/schema
AGENTLOOM_LLM_RESPONSE_FORMAT=json_schema
```

使用 LiteLLM 支持的模型时，设置：

```dotenv
AGENTLOOM_LLM_PROVIDER=litellm
AGENTLOOM_LLM_MODEL=openai/gpt-4.1-mini
AGENTLOOM_LLM_RESPONSE_FORMAT=json_schema
OPENAI_API_KEY=replace-with-your-key
```

对于支持 JSON 对象但不接受严格 JSON Schema 的 OpenAI 兼容接口，使用：

```dotenv
AGENTLOOM_LLM_PROVIDER=litellm
AGENTLOOM_LLM_MODEL=openai/provider-model-id
AGENTLOOM_LLM_RESPONSE_FORMAT=json_object
OPENAI_BASE_URL=https://provider.example/v1
OPENAI_API_KEY=replace-with-your-key
```

`json_schema` 仍为默认模式，由模型提供商执行严格校验。`json_object` 兼容模式依赖 AgentLoom 本地的 Pydantic、DAG 和 Reviewer 校验。请按照 LiteLLM 对相应模型提供商的要求设置环境变量。切勿提交 `.env` 或 API 密钥。`AGENTLOOM_LLM_TIMEOUT_SECONDS` 用于限制每次模型调用的时长，`AGENTLOOM_WORKER_MAX_TURNS` 用于限制每个 Worker 的工具调用循环次数。

## 运行测试和检查

后端测试使用 PostgreSQL，但不需要模型 API 密钥：

```powershell
uv run --locked pytest -m "not live" --cov=agentloom --cov-report=term-missing
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
```

前端检查同样可以完全离线运行：

```powershell
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
```

首次运行前安装一次 Chromium，然后执行完整的产品研究浏览器流程：

```powershell
Set-Location frontend
npx playwright install chromium
npm run test:e2e
Set-Location ..
```

E2E 测试会启动隔离的 FastAPI 和 Vite 进程，使用确定性的 MockLLM，覆盖一次 Reviewer 重试，并且需要配置好的 PostgreSQL 数据库。

## 数据库迁移

在仓库根目录执行和检查数据库迁移：

```powershell
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
```

启动 Uvicorn 前，请先应用已提交的数据库迁移。`0.1.0` 版本仅运行一个后端实例；恢复和调度采用单进程所有权模型。

## 运行时行为

- 启动恢复会查找处于排队或运行状态的运行记录（Run），保留已完成节点，重置被中断的运行中或审核中尝试，记录 `run.recovered` 事件，然后恢复调度。
- 取消运行会将所有未完成的尝试标记为已取消。已经发出的模型调用可能仍会结束，但其输出无法再触发状态转换或写入结果。
- 重试失败的运行会使用相同的不可变工作流和输入创建一条新运行记录。失败的原运行记录会继续保留，供历史查询。
- SSE 事件会先持久化再发送通知，支持事件重放；运行完成、失败或取消后，界面会关闭对应连接。

## 发布检查

运行完整的本地发布检查：

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

仓库内包含 GitHub Actions 工作流，它会在 PostgreSQL 16 环境中执行同等的离线后端、前端、数据库迁移和 Playwright 检查。
