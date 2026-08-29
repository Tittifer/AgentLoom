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
  it("展示 Queen 消息并发送用户输入", async () => {
    const onSend = vi.fn(async () => undefined);
    render(<ChatPanel messages={[message]} onSend={onSend} sending={false} session={session} />);
    expect(screen.getByText("已经完成分析。")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("发送给 Queen 的消息"), "继续执行");
    await userEvent.click(screen.getByRole("button", { name: "发送给 Queen" }));
    expect(onSend).toHaveBeenCalledWith("继续执行");
  });
});
