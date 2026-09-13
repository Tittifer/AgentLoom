import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { WorkerRead } from "../../src/api/colonies";
import { WorkerDrawer } from "../../src/components/WorkerDrawer";

const worker: WorkerRead = {
  layout_version: 2,
  id: "worker-1",
  colony_id: "colony-1",
  owner_session_id: "queen-1",
  queen_id: "queen_general",
  status: "completed",
  park_reason: null,
  task: "调研目标城市",
  input: { city: "不应显示的内部输入" },
  report: { status: "success", summary: "已完成城市调研。", data: { score: 9 } },
  error: null,
  cursor: {},
  budget: {},
  usage: {},
  timeout_seconds: 60,
  queued_at: "2026-08-30T00:00:00Z",
  started_at: "2026-08-30T00:00:01Z",
  updated_at: "2026-08-30T00:00:02Z",
  ended_at: "2026-08-30T00:00:02Z",
};

describe("WorkerDrawer", () => {
  it("只展示可读的工作摘要", () => {
    render(<WorkerDrawer onClose={vi.fn()} worker={worker} />);

    expect(screen.getByText("软超时")).toBeInTheDocument();
    expect(screen.getByText("60 秒")).toBeInTheDocument();
    expect(screen.getByText("已完成城市调研。")).toBeInTheDocument();
    expect(screen.queryByText(/不应显示的内部输入/)).not.toBeInTheDocument();
    expect(screen.queryByText(/"score"/)).not.toBeInTheDocument();
  });
});
