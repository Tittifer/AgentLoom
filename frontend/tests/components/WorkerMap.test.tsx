import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { SessionRead, WorkerRead } from "../../src/api/colonies";
import { WorkerMap } from "../../src/components/WorkerMap";

const queen = {
  id: "q", colony_id: "c", parent_session_id: null, actor_type: "queen", status: "running",
  park_reason: null, task: {}, cursor: {}, budget: {}, usage: {},
  created_at: "2026-08-29T00:00:00Z", updated_at: "2026-08-29T00:00:00Z", ended_at: null,
} satisfies SessionRead;
const worker = {
  id: "w", colony_id: "c", queen_session_id: "q", worker_session_id: "ws",
  status: "completed", task: "收集竞品资料", input: {}, report: { summary: "完成" },
  error: null, timeout_seconds: 60, queued_at: "2026-08-29T00:00:00Z",
  started_at: "2026-08-29T00:00:01Z", ended_at: "2026-08-29T00:00:02Z",
} satisfies WorkerRead;

describe("WorkerMap", () => {
  it("展示动态 Worker 并支持选择", async () => {
    const onSelect = vi.fn();
    render(<WorkerMap onSelect={onSelect} queen={queen} workers={[worker]} />);
    expect(screen.getByText("任务协调者")).toBeInTheDocument();
    expect(screen.getByText("主节点 · Queen")).toBeInTheDocument();
    expect(screen.getByText("任务分派")).toBeInTheDocument();
    expect(screen.getByText("从节点 1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /收集竞品资料/ }));
    expect(onSelect).toHaveBeenCalledWith(worker);
  });

  it("使用简短标题展示长任务并保留完整内容入口", () => {
    const longTask = "调研旅游城市【杭州】：请汇总核心游玩景点、代表性美食、人均预算、最佳季节和适合人群";
    render(
      <WorkerMap
        onSelect={vi.fn()}
        queen={queen}
        workers={[{ ...worker, status: "running", task: longTask }]}
      />,
    );

    const node = screen.getByRole("button", { name: /调研旅游城市【杭州】/ });
    expect(node).toHaveAttribute("title", longTask);
    expect(node).toHaveTextContent("从节点 1");
    expect(node).not.toHaveTextContent("请汇总核心游玩景点");
    expect(node).toHaveTextContent("运行中");
  });
});
