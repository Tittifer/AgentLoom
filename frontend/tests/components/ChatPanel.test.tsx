import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { MessageRead, SessionRead } from "../../src/api/colonies";
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

describe("ChatPanel", () => {
  it("只展示用户与 AgentLoom 的最终消息并发送用户输入", async () => {
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
        messages={[...internalMessages, message]}
        onSend={onSend}
        sending={false}
        session={session}
      />,
    );
    expect(screen.getByText("已经完成分析。")).toBeInTheDocument();
    expect(screen.queryByText(/内部工具数据/)).not.toBeInTheDocument();
    expect(screen.queryByText(/内部汇报/)).not.toBeInTheDocument();
    expect(screen.queryByText(/正在安排内部任务/)).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("输入消息"), "继续执行");
    await userEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(onSend).toHaveBeenCalledWith("继续执行");
  });
});
