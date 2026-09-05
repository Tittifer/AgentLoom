# AgentLoom

AgentLoom 是一个基于 Hive Colony 思路实现的持久化多智能体协作应用。Queen 身份与会话分离：同一个 Queen 可以拥有多条彼此隔离的 Colony 会话；每个 Colony 会话持续维护自己的消息、任务、Tracker 和 Worker。Queen 按实际需要动态派生多个并行 Worker，系统不预先生成固定 DAG，也不要求用户手动填写 Context JSON。

## 核心能力

- Queen 多轮会话：用户可以持续补充信息、调整目标或追问结果。
- Queen 身份管理：身份、系统提示词、模型协议与连接配置保存在独立 YAML Profile 中，会话只引用稳定的 `queen_id`。
- 会话隔离：同一 Queen 下的不同会话不共享消息、预算、Worker、Task 或 Tracker。
- 动态 Worker：Queen 通过 `run_worker` 即时创建一个或多个并行 Worker。
- 独立 AgentLoop：每个 Queen 会话保持自己的长期循环，每个 Worker 创建自己的循环实例；两类智能体共用相同的模型调用、工具、质量检查、用量统计和持久化协议。
- 共享状态：任务计划保存在会话文件中，每个 Colony 使用独立的 SQLite Tracker。
- 可恢复执行：消息、会话游标、Worker 状态和事件均持久化；进程重启会重新排队被中断的执行。
- 预算安全收尾：工作预算耗尽后进入受限 Grace 阶段；Worker 保证向 Queen 汇报，Queen 保持可继续对话。
- 终态报告兜底：Worker 异常或超时仍会生成结构化失败报告并唤醒 Queen，避免批量任务永久等待。
- 实时工作台：React 界面通过 SSE 展示 Queen、Worker、任务和 Tracker 的变化。
- 模型兼容：根据 Queen 的模型名称自动选择 OpenAI、Claude 或 Gemini 协议，并通过 LiteLLM 调用。

## 目录结构

```text
agentloom/                 FastAPI 后端包
  agents/                 AgentLoop 实现与 Judge
  api/routes/colonies.py  Colony、会话和 SSE API
  colony/                 Colony DTO、通知器和运行时
  storage/                Queen Profile、会话文件与每 Colony SQLite Tracker
  llm/                    Mock 与 LiteLLM 适配器
  tools/                  有界只读工具注册表
frontend/                 React Colony 工作台
tests/agentloom/          与后端源码路径对应的单元测试
tests/integration/        本地持久化和 HTTP 集成测试
tests/contract/           LiteLLM 适配器契约测试
dev.py                    前后端一键启动脚本
```

## 环境要求

- Python 3.11
- uv
- Node.js 22 和 npm 10
- GNU Make（可选；Windows 也可以直接运行脚本）

## 环境变量

AgentLoom 不读取 `.env`。持久化根目录固定为项目根目录下的 `.agentloom`。

首次启动后在 Queen 页面创建 Queen，并填写模型名称、没有 API 路径后缀的服务 Base URL 和 API Key。后端根据模型名称自动选择协议：`claude-*` 使用 Claude 协议，`gemini-*` 使用 Gemini 协议，其他模型使用 OpenAI 兼容协议。OpenAI 兼容协议会自动给 Base URL 添加 `/v1`。

Queen 配置保存在 `queens/<queen_id>/profile.yaml`，`queen_id` 由后端根据名称自动生成。API Key 只保存在本机 YAML 中，不会通过 Queen 查询接口返回；`.agentloom/` 已被 Git 忽略。旗下 Session 引用保存在 `sessions/`，每个 Colony 是一个自包含目录。除每个 Colony 的 `tracker/tracker.db` 外，其余运行状态使用 JSON、JSONL 和普通文件保存。

## 安装和启动

```powershell
uv sync --locked --all-groups
npm --prefix frontend ci
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
POST /api/queens
GET  /api/queens
GET  /api/queens/{queen_id}
GET  /api/queens/{queen_id}/sessions
```

SSE 事件先追加到 Colony 的 `events.jsonl`，再通知客户端；客户端可用 `after` 序号重放断线期间的事件。

## 测试与检查

后端测试使用临时本地存储目录，不依赖外部数据库服务：

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
- 每个 Colony 预留独立的 `artifacts/` 目录；大文件 Artifact API 尚未实现。
- 本项目不包含生产 Docker 部署方案。
