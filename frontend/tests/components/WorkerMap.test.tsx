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
    expect(screen.getByText("Queen")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /收集竞品资料/ }));
    expect(onSelect).toHaveBeenCalledWith(worker);
  });
});
