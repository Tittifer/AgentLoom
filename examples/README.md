# 示例

AgentLoom 不再依赖预先定义的固定 Workflow JSON。创建 Colony 后，可以直接向 Queen 发送类似下面的目标：

```text
比较三个主流代码智能体产品。请把资料收集拆成可并行的 Worker，
将关键事实和来源写入共享 Tracker，最后给出包含对比表和建议的中文报告。
```

Queen 会根据模型判断动态创建任务计划和 Worker。离线 Mock 模式只验证会话链路；需要真实研究结果时，请在 `.env` 中配置真实 LiteLLM 提供商和具备相应能力的工具。
