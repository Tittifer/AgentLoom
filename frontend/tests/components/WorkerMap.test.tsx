import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { WorkerRead } from "../../src/api/colonies";
import { WorkerMap } from "../../src/components/WorkerMap";

const worker = {
  id: "w", colony_id: "c", queen_session_id: "q", worker_session_id: "ws",
  status: "completed", task: "收集竞品资料", input: {}, report: { summary: "完成" },
  error: null, timeout_seconds: 60, queued_at: "2026-08-29T00:00:00Z",
  started_at: "2026-08-29T00:00:01Z", ended_at: "2026-08-29T00:00:02Z",
} satisfies WorkerRead;

describe("WorkerMap", () => {
  it("展示动态 Worker 并支持选择", async () => {
    const onSelect = vi.fn();
    render(<WorkerMap onSelect={onSelect} workers={[worker]} />);
    expect(screen.getByRole("heading", { name: "Workers" })).toBeInTheDocument();
    expect(screen.getByText("独立 AgentLoop · 60 秒软超时")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /收集竞品资料/ }));
    expect(onSelect).toHaveBeenCalledWith(worker);
  });

  it("完整展示 Worker 任务并保留详情入口", () => {
    const longTask = "调研旅游城市【杭州】：请汇总核心游玩景点、代表性美食、人均预算、最佳季节和适合人群";
    render(
      <WorkerMap
        onSelect={vi.fn()}
        workers={[{ ...worker, status: "running", task: longTask }]}
      />,
    );

    const button = screen.getByRole("button", { name: /调研旅游城市【杭州】/ });
    const card = button.closest("article");
    expect(card).toHaveTextContent(longTask);
    expect(card).toHaveTextContent("运行中");
  });
});
