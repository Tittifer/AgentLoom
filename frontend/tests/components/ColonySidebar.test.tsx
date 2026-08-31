import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { SessionRead, TrackerEntryRead } from "../../src/api/colonies";
import { ColonySidebar } from "../../src/components/ColonySidebar";

const queen: SessionRead = {
  id: "queen-1", colony_id: "colony-1", parent_session_id: null, actor_type: "queen",
  status: "idle", park_reason: null, task: {}, cursor: {}, budget: {}, usage: {},
  created_at: "2026-08-30T00:00:00Z", updated_at: "2026-08-30T00:00:00Z", ended_at: null,
};

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
  it("通过标签切换并以自然语言展示阶段性结果", async () => {
    render(
      <ColonySidebar
        onSelectWorker={vi.fn()}
        queen={queen}
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
