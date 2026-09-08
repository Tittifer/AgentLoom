# AgentLoom

AgentLoom 是一个基于 Hive Colony 思路实现的持久化多智能体协作应用。Queen 身份与会话分离：新会话先以独立 DM 运行；只有当 Queen 判断任务需要并行协作并得到用户确认后，才会分叉为 Colony。每个 Colony 持续维护自己的消息、任务、Tracker 和 Worker。

## 核心能力

- Queen 多轮会话：用户可以持续补充信息、调整目标或追问结果。
- Colony 显式分叉：独立 Queen 只能提交建议；用户确认后系统复制完整对话、初始化任务和 Tracker，并锁定源 DM。
- Queen 身份管理：身份和系统提示词保存在独立 YAML Profile 中，会话只引用稳定的 `queen_id`；模型连接由全局用户设置统一管理。
- 会话隔离：同一 Queen 下的不同会话不共享消息、预算、Worker、Task 或 Tracker。
- 动态 Worker：Queen 通过 `run_worker` 即时创建一个或多个并行 Worker。
- 独立 AgentLoop：每个 Queen 会话保持自己的长期循环，每个 Worker 创建自己的循环实例；两类智能体共用相同的模型调用、工具、质量检查、用量统计和持久化协议。
- 共享状态：任务计划保存在会话文件中，每个 Colony 使用独立的 SQLite Tracker。
- 可恢复执行：消息、会话游标、Worker 状态和事件均持久化；进程重启会重新排队被中断的执行。
- 预算安全收尾：工作预算耗尽后进入受限 Grace 阶段；Worker 保证向 Queen 汇报，Queen 保持可继续对话。
- 终态报告兜底：Worker 异常或超时仍会生成结构化失败报告并唤醒 Queen，避免批量任务永久等待。
- 实时工作台：React 界面通过 SSE 展示 Queen、Worker、任务和 Tracker 的变化。
- 模型兼容：根据全局用户设置中的模型名称自动选择 OpenAI、Claude 或 Gemini 协议，并通过 LiteLLM 调用。
- 长期记忆：后台 Reflection 从 Queen 对话提炼 global/Queen 两级 Markdown 记忆，并在后续请求中按相关性召回。
- 上下文压缩：Queen 和每个 Worker 分别按模型窗口执行工具结果落盘、微压缩和 LLM 摘要压缩，完整聊天记录不受影响。

## 目录结构

```text
agentloom/                 FastAPI 后端包
  agents/                 AgentLoop 实现与 Judge
  context/                Token 估算、上下文策略和摘要压缩
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

首次启动后先进入顶部“设置”页面，填写全局模型名称、不带 API 路径后缀的服务 Base URL 和 API Key，再创建 Queen。后端根据模型名称自动选择协议：`claude-*` 使用 Claude 协议，`gemini-*` 使用 Gemini 协议，其他模型使用 OpenAI 兼容协议。OpenAI 兼容协议会自动给 Base URL 添加 `/v1`。

全局模型配置保存在 `.agentloom/settings.yaml`；Queen 身份配置保存在 `queens/<queen_id>/profile.yaml`，`queen_id` 由后端根据名称自动生成。API Key 只保存在本机设置文件中，不会通过查询接口返回；`.agentloom/` 已被 Git 忽略。独立 DM 保存在 `queens/<queen_id>/sessions/<session_id>/`，删除后会整体移动到 `.agentloom/trash/session-<session_id>-<uuid>/`，便于恢复。每个 Colony 则是 `colonies/<colony_id>/` 下的自包含目录。除每个 Colony 的 `tracker/tracker.db` 外，其余运行状态使用 JSON、JSONL 和普通文件保存。

长期记忆保存在 `.agentloom/memories/global/*.md` 和 `.agentloom/memories/agents/queens/<queen_id>/*.md`。每条记忆包含 YAML frontmatter 和 Markdown 正文，单文件最多 4096 字节。Worker 不自动继承这些记忆；可以通过顶部“记忆”页面查看、编辑或删除。

模型上下文窗口在全局“设置”页面配置，并动态应用到所有 Queen 与 Worker 的 AgentLoop。压缩 checkpoint 位于 Session 的 `context/compaction.json`；超过限制的完整工具结果保存在 `spillover/*.json`，模型通过 `load_tool_result` 分页读取。`conversations/parts/*.json` 原始消息不会因压缩删除，因此前端仍展示完整对话。

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

1. 点击“新建会话”后进入独立 Queen DM，此时不创建 Tracker 或 Worker。
2. Queen 先直接处理目标；当任务适合并行、周期性或长期运行时，在右侧提交 Colony 建议。
3. 用户可以修改名称和目标后确认，也可暂不创建。确认后会话全链路复制到新 Colony，源 DM 转为只读并保留跳转关系。
4. Colony Queen 可创建任务、写入共享 Tracker，并按需要派生多个并行 Worker。
5. Worker 独立执行并向 Queen 汇报，Queen 综合结果后回复用户。

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
POST /api/queens/{queen_id}/sessions
POST /api/sessions/{session_id}/fork-colony
POST /api/sessions/{session_id}/dismiss-colony-suggestion
GET  /api/sessions/{session_id}/events
```

SSE 事件先追加到 Colony 或独立 DM 的 `events.jsonl`，再通知客户端；客户端可用 `after` 序号重放断线期间的事件。

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
