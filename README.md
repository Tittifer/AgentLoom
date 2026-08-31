# AgentLoom

AgentLoom 是一个基于 Hive Colony 思路实现的持久化多智能体协作应用。每个 Colony 拥有一个长期存在的 Queen 会话；Queen 持续与用户对话、维护任务计划和共享 Tracker，并按实际需要动态派生多个并行 Worker。系统不再预先生成固定 DAG，也不要求用户手动填写 Context JSON。

## 核心能力

- Queen 多轮会话：用户可以持续补充信息、调整目标或追问结果。
- 动态 Worker：Queen 通过 `run_worker` 即时创建一个或多个并行 Worker。
- 统一 AgentLoop：Queen 和 Worker 共用模型调用、工具循环、质量检查、用量统计和持久化边界。
- 共享状态：任务计划和 Tracker 保存在 PostgreSQL 中，所有智能体可读写。
- 可恢复执行：消息、会话游标、Worker 状态和事件均持久化；进程重启会重新排队被中断的执行。
- 实时工作台：React 界面通过 SSE 展示 Queen、Worker、任务和 Tracker 的变化。
- 模型兼容：离线开发使用 MockLLM，真实模型通过 LiteLLM 接入 OpenAI 兼容接口或其他提供商。

## 目录结构

```text
agentloom/                 FastAPI 后端包
  agents/                 统一 AgentLoop 与 Judge
  api/routes/colonies.py  Colony、会话和 SSE API
  colony/                 Colony DTO、通知器和运行时
  db/models/              Colony 持久化模型
  repositories/           Colony 聚合仓储
  llm/                    Mock 与 LiteLLM 适配器
  tools/                  有界只读工具注册表
frontend/                 React Colony 工作台
tests/agentloom/          与后端源码路径对应的单元测试
tests/integration/        PostgreSQL 和 HTTP 集成测试
tests/contract/           LiteLLM 适配器契约测试
alembic/                  数据库迁移
dev.py                    前后端一键启动脚本
```

早期版本的 Task、Workflow、Run 表由历史迁移保留，方便已有数据库升级；当前应用代码和 HTTP API 已不再读写这些旧表。

## 环境要求

- Python 3.11
- uv
- Node.js 22 和 npm 10
- PostgreSQL 16
- GNU Make（可选；Windows 也可以直接运行脚本）

## 环境变量

先复制示例文件：

```powershell
Copy-Item .env.example .env
```

主要配置如下：

```dotenv
AGENTLOOM_ENV=development
AGENTLOOM_LOG_LEVEL=INFO
AGENTLOOM_DATABASE_URL=postgresql+asyncpg://agentloom:agentloom@localhost:5432/agentloom

AGENTLOOM_LLM_PROVIDER=mock
AGENTLOOM_LLM_MODEL=mock/schema
AGENTLOOM_LLM_RESPONSE_FORMAT=json_schema
AGENTLOOM_LLM_TIMEOUT_SECONDS=60

AGENTLOOM_QUEEN_MAX_TURNS=20
AGENTLOOM_MAX_CONCURRENT_WORKERS=4
AGENTLOOM_WORKER_TIMEOUT_SECONDS=600
```

`.env.example` 的数据库端口是开发用 Compose 默认端口 `15432`。如果使用本机 PostgreSQL，通常将其改成 `5432`。

### 第三方 OpenAI 兼容模型

```dotenv
AGENTLOOM_LLM_PROVIDER=litellm
AGENTLOOM_LLM_MODEL=openai/你的模型名称
AGENTLOOM_LLM_RESPONSE_FORMAT=json_object
OPENAI_BASE_URL=https://你的服务地址/v1
OPENAI_API_KEY=你的密钥
```

如果提供商完整支持严格 JSON Schema，可将 `AGENTLOOM_LLM_RESPONSE_FORMAT` 改成 `json_schema`。不要提交 `.env` 或真实 API 密钥。

## 安装、迁移和启动

```powershell
uv sync --locked --all-groups
npm --prefix frontend ci
uv run --locked alembic upgrade head
```

一键启动前后端：

```powershell
make dev
```

Windows 未安装 `make` 时使用：

```powershell
uv run --locked python dev.py
```

启动后访问：

- 前端工作台：<http://localhost:5173/colonies>
- 后端健康检查：<http://localhost:8000/health>
- OpenAPI：<http://localhost:8000/docs>

## 使用流程

1. 点击“新建会话”后会直接进入工作区；发送第一条消息时，系统会据此生成会话名称并使用默认协作配置。
2. 主智能体可以创建任务项、写入共享状态，并按需要派生多个并行协作节点。
3. 协作节点独立执行任务并向主智能体汇报；内部工具消息和结构化数据不会显示在用户对话中。
4. 主智能体综合协作结果后回复用户，用户可以继续补充信息或调整要求。
5. 不再需要的会话可以从会话列表或会话页面删除。

## 主要 API

```text
POST /api/colonies
GET  /api/colonies
GET  /api/colonies/{colony_id}
DELETE /api/colonies/{colony_id}
GET  /api/sessions/{session_id}
GET  /api/sessions/{session_id}/messages
POST /api/sessions/{session_id}/messages
GET  /api/colonies/{colony_id}/workers
GET  /api/colonies/{colony_id}/tasks
GET  /api/colonies/{colony_id}/tracker
GET  /api/colonies/{colony_id}/events
```

SSE 事件先写入 PostgreSQL，再通知客户端；客户端可用 `after` 序号重放断线期间的事件。

## 测试与检查

后端测试会连接 `.env` 指定的 PostgreSQL：

```powershell
uv run --locked pytest --cov=agentloom --cov-report=term-missing
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
```

前端检查：

```powershell
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
```

也可以运行 `make check` 执行完整检查。当前后端覆盖率门槛为 80%。

## 当前边界

- 当前版本面向单个可信用户，不包含登录、租户隔离和细粒度权限。
- Worker 并发由单进程 `asyncio` 信号量控制，不是分布式队列。
- 内置 `web_search` 是离线确定性示例；接入真实搜索或 MCP 工具前应增加权限、审计和速率限制。
- Artifact 表已经建立，但大文件对象存储适配器尚未实现。
- 本项目不包含生产 Docker 部署方案。
