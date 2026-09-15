import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listDataRows, listDataTables } from "../../src/api/colonyData";
import { ColonySidebar } from "../../src/components/ColonySidebar";

vi.mock("../../src/api/colonyData", () => ({
  listDataTables: vi.fn(),
  listDataRows: vi.fn(),
}));

function renderSidebar(colonyId?: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ColonySidebar
        colonyId={colonyId}
        onSelectWorker={vi.fn()}
        tasks={[]}
        workers={[]}
      />
    </QueryClientProvider>,
  );
}

describe("ColonySidebar", () => {
  beforeEach(() => {
    vi.mocked(listDataTables).mockResolvedValue([]);
    vi.mocked(listDataRows).mockResolvedValue({
      table: "city_research",
      columns: [],
      primary_key: [],
      rows: [],
      total: 0,
      limit: 100,
      offset: 0,
    });
  });
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("空状态展示三个 Colony 工作区标签", () => {
    renderSidebar();

    expect(screen.getAllByRole("tab")).toHaveLength(3);
    expect(screen.getByText("暂无数据")).toBeInTheDocument();
  });

  it("展示真实业务表的列、主键和结构化行", async () => {
    vi.mocked(listDataTables).mockResolvedValue([{
      name: "city_research",
      columns: [
        { name: "city", type: "TEXT", notnull: true, primary_key_position: 1, default: null },
        { name: "facts_json", type: "TEXT", notnull: false, primary_key_position: 0, default: null },
      ],
      row_count: 1,
      primary_key: ["city"],
    }]);
    vi.mocked(listDataRows).mockResolvedValue({
      table: "city_research",
      columns: [
        { name: "city", type: "TEXT", notnull: true, primary_key_position: 1, default: null },
        { name: "facts_json", type: "TEXT", notnull: false, primary_key_position: 0, default: null },
      ],
      primary_key: ["city"],
      rows: [{ city: "杭州", facts_json: '{"ready":true,"tags":["西湖","龙井"]}' }],
      total: 1,
      limit: 100,
      offset: 0,
    });
    renderSidebar("colony-1");

    await userEvent.click(screen.getByRole("tab", { name: /数据/ }));

    expect(await screen.findByText("杭州")).toBeInTheDocument();
    expect(screen.getByText("PK")).toBeInTheDocument();
    expect(screen.getByText("ready：是；tags：西湖、龙井")).toBeInTheDocument();
  });
});
