import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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
  it("以自然语言展示阶段性结果而不是 JSON", () => {
    render(<ColonySidebar tasks={[]} tracker={[tracker]} />);

    expect(screen.getByText("北京、上海")).toBeInTheDocument();
    expect(screen.getByText("是")).toBeInTheDocument();
    expect(screen.queryByText(/\{"cities"/)).not.toBeInTheDocument();
  });
});
