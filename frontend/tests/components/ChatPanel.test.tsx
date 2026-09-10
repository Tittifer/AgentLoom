import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { MessageRead, SessionRead, WorkerRead } from "../../src/api/colonies";
import { ChatPanel } from "../../src/components/ChatPanel";

const session: SessionRead = {
  id: "session-1", colony_id: "colony-1", parent_session_id: null,
  actor_type: "queen", status: "idle", park_reason: null, task: {}, cursor: {},
  budget: {}, usage: {}, created_at: "2026-08-29T00:00:00Z",
  updated_at: "2026-08-29T00:00:00Z", ended_at: null,
};

const message: MessageRead = {
  id: "message-1", session_id: session.id, sequence: 1, role: "assistant",
  content: "已经完成分析。", tool_call_id: null, tool_calls: [], metadata: {},
  created_at: "2026-08-29T00:00:00Z",
};

const worker: WorkerRead = {
  id: "worker-1", colony_id: "colony-1", queen_session_id: session.id,
  worker_session_id: "worker-session-1", status: "completed", task: "整理内部资料",
  input: {}, report: { summary: "摘要" }, error: null, timeout_seconds: 60,
  queued_at: "2026-08-29T00:00:01Z", started_at: "2026-08-29T00:00:02Z",
  ended_at: "2026-08-29T00:00:04Z",
};

describe("ChatPanel", () => {
  it("展示最终消息与执行链并发送用户输入", async () => {
    const onSend = vi.fn(async () => undefined);
    const internalMessages: MessageRead[] = [
      {
        ...message,
        id: "tool-message",
        role: "tool",
        content: '{"result":"内部工具数据"}',
      },
      {
        ...message,
        id: "worker-report",
        role: "user",
        content: "[WORKER_REPORT] 内部汇报",
        metadata: { worker_run_id: "worker-1" },
      },
      {
        ...message,
        id: "tool-call",
        content: "正在安排内部任务",
        tool_calls: [{ id: "call-1", name: "run_worker", arguments: {} }],
      },
    ];
    render(
      <ChatPanel
        activeWorkerCount={0}
        messages={[...internalMessages, message]}
        onSend={onSend}
        sending={false}
        session={session}
        streamingMessage={null}
      />,
    );
    expect(await screen.findByText("已经完成分析。")).toBeInTheDocument();
    expect(screen.queryByText(/内部工具数据/)).not.toBeInTheDocument();
    expect(screen.getByText(/内部汇报/)).toBeInTheDocument();
    expect(screen.getByText(/正在安排内部任务/)).toBeInTheDocument();
    expect(screen.getByText(/run_worker/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("输入消息"), "继续执行");
    await userEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(onSend).toHaveBeenCalledWith("继续执行");
  });

  it("Worker 执行期间显示动态等待状态", () => {
    render(
      <ChatPanel
        activeWorkerCount={3}
        messages={[]}
        onSend={vi.fn(async () => undefined)}
        sending={false}
        session={{ ...session, status: "idle" }}
        streamingMessage={null}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("3 个协作节点正在执行任务");
  });

  it("把 Worker 和报告合并为对话时间线中的执行卡片", () => {
    const { container } = render(
      <ChatPanel
        activeWorkerCount={0}
        messages={[{
          ...message,
          id: "worker-report",
          role: "user",
          content: '[WORKER_REPORT]\n{"status":"completed","summary":"**完整报告**"}',
          metadata: { worker_run_id: worker.id },
          created_at: "2026-08-29T00:00:05Z",
        }]}
        onSend={vi.fn(async () => undefined)}
        sending={false}
        session={session}
        streamingMessage={null}
        workers={[worker]}
      />,
    );

    expect(screen.getByText("整理内部资料")).toBeInTheDocument();
    expect(screen.getByText("完整报告")).toBeInTheDocument();
    expect(container.querySelectorAll(".hive-worker-card")).toHaveLength(1);
    expect(container.querySelector(".worker-activity-card")).not.toBeInTheDocument();
  });

  it("直接展示后端推送的增量文本，不回放已持久化消息", () => {
    const { container } = render(
      <ChatPanel
        activeWorkerCount={0}
        messages={[message]}
        onSend={vi.fn(async () => undefined)}
        sending={false}
        session={{ ...session, status: "running" }}
        streamingMessage={{ id: "stream-1", content: "正在实时生成" }}
      />,
    );

    expect(screen.getByText("正在实时生成")).toBeInTheDocument();
    expect(screen.getByText("正在生成")).toBeInTheDocument();
    expect(container.querySelector(".agent-waiting")).not.toBeInTheDocument();
  });

  it("shows the current LLM retry delay", () => {
    render(
      <ChatPanel
        activeWorkerCount={0}
        llmRetry={{
          category: "capacity",
          attempt: 3,
          maxRetries: null,
          delaySeconds: 8,
        }}
        messages={[]}
        onSend={vi.fn(async () => undefined)}
        sending={false}
        session={{ ...session, status: "running" }}
        streamingMessage={null}
      />,
    );

    expect(screen.getByText("模型服务繁忙，8 秒后继续重试（第 3 次）")).toBeInTheDocument();
  });

  it("renders assistant Markdown for persisted and streaming messages", () => {
    const markdownMessage = {
      ...message,
      content: "## 城市推荐\n\n| 城市 | 特色 |\n| --- | --- |\n| 成都 | **熊猫** |",
    };
    const { container } = render(
      <ChatPanel
        activeWorkerCount={0}
        messages={[markdownMessage]}
        onSend={vi.fn(async () => undefined)}
        sending={false}
        session={{ ...session, status: "running" }}
        streamingMessage={{ id: "stream-2", content: "### 正在汇总\n\n- 杭州" }}
      />,
    );

    expect(screen.getByRole("heading", { level: 2, name: "城市推荐" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "正在汇总" })).toBeInTheDocument();
    expect(container.querySelector(".streaming-cursor")).toBeInTheDocument();
  });
});
