import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TrackerEntryRead } from "../../src/api/colonies";
import { ColonySidebar } from "../../src/components/ColonySidebar";

const tracker: TrackerEntryRead = {
  id: "tracker-1",
  colony_id: "colony-1",
  namespace: "travel",
  entry_key: "city_comparison",
  status: "in_progress",
  data: { cities: ["北京", "上海"], ready: true },
  version: 1,
  updated_by_session_id: null,
  created_at: "2026-08-30T00:00:00Z",
  updated_at: "2026-08-30T00:00:00Z",
};

describe("ColonySidebar", () => {
  afterEach(cleanup);

  it("空状态仍展示四个 Colony 工作区标签", () => {
    render(
      <ColonySidebar
        onSelectWorker={vi.fn()}
        tasks={[]}
        tracker={[]}
        workers={[]}
      />,
    );

    expect(screen.getAllByRole("tab")).toHaveLength(4);
    expect(screen.getByText("暂无数据")).toBeInTheDocument();
  });

  it("通过标签切换并以自然语言展示阶段性结果", async () => {
    render(
      <ColonySidebar
        onSelectWorker={vi.fn()}
        tasks={[]}
        tracker={[tracker]}
        workers={[]}
      />,
    );

    await userEvent.click(screen.getByRole("tab", { name: /数据/ }));

    expect(screen.getByText("北京、上海")).toBeInTheDocument();
    expect(screen.getByText("是")).toBeInTheDocument();
    expect(screen.queryByText(/\{"cities"/)).not.toBeInTheDocument();
  });
});
