import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { WorkerRead } from "../../src/api/colonies";
import { WorkerCard } from "../../src/components/WorkerCard";

const worker: WorkerRead = {
  id: "worker-12345678",
  colony_id: "colony-1",
  queen_session_id: "queen-1",
  worker_session_id: "worker-session-1",
  status: "completed",
  task: "分析 Hive 的 Worker 展示方式",
  input: {},
  report: { summary: "已经完成界面对比。" },
  error: null,
  timeout_seconds: 300,
  queued_at: "2026-09-08T08:00:00Z",
  started_at: "2026-09-08T08:00:01Z",
  ended_at: "2026-09-08T08:00:04Z",
};

describe("WorkerCard", () => {
  it("展示 Hive 式 Worker 执行信息并打开详情", async () => {
    const onSelect = vi.fn();
    render(<WorkerCard onSelect={onSelect} worker={worker} />);

    expect(screen.getByText("Worker")).toBeInTheDocument();
    expect(screen.getByText("worker-1")).toBeInTheDocument();
    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(screen.getByText("3 秒")).toBeInTheDocument();
    expect(screen.getByText("分析 Hive 的 Worker 展示方式")).toBeInTheDocument();
    expect(screen.getByText("已经完成界面对比。")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /分析 Hive 的 Worker 展示方式/ }));
    expect(onSelect).toHaveBeenCalledWith(worker);
  });

  it("执行中显示状态文案", () => {
    render(<WorkerCard worker={{ ...worker, ended_at: null, report: null, status: "running" }} />);

    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.getByText("正在独立执行任务…")).toBeInTheDocument();
  });
});
