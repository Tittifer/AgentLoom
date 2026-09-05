import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueen, listQueens, type QueenRead } from "../../src/api/queens";
import { QueenListPage } from "../../src/pages/QueenListPage";

vi.mock("../../src/api/queens", () => ({
  createQueen: vi.fn(),
  listQueens: vi.fn(),
}));

const generalQueen: QueenRead = {
  id: "general",
  name: "AgentLoom",
  description: "通用 Queen",
  system_prompt: "负责协调任务。",
  default_model: "mock/schema",
  settings: {},
  created_at: "2026-09-05T00:00:00Z",
  updated_at: "2026-09-05T00:00:00Z",
};

describe("QueenListPage", () => {
  beforeEach(() => {
    vi.mocked(listQueens).mockResolvedValue([generalQueen]);
    vi.mocked(createQueen).mockReset();
  });

  it("创建 Queen 后进入它的会话列表", async () => {
    vi.mocked(createQueen).mockResolvedValue({
      ...generalQueen,
      id: "research",
      name: "研究 Queen",
      description: "负责研究任务",
      system_prompt: "你负责研究和整理资料。",
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/queens"]}>
          <Routes>
            <Route path="/queens" element={<QueenListPage />} />
            <Route path="/queens/:queenId" element={<div>Queen 会话列表</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("AgentLoom")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "新建 Queen" }));
    await userEvent.type(screen.getByLabelText(/唯一 ID/), "research");
    await userEvent.type(screen.getByLabelText("名称"), "研究 Queen");
    await userEvent.type(screen.getByLabelText("描述"), "负责研究任务");
    await userEvent.type(screen.getByLabelText("系统提示词"), "你负责研究和整理资料。");
    expect(screen.getByLabelText("默认模型")).toHaveValue("mock/schema");
    await userEvent.click(screen.getByRole("button", { name: "创建 Queen" }));

    expect(vi.mocked(createQueen).mock.calls[0]?.[0]).toEqual({
      id: "research",
      name: "研究 Queen",
      description: "负责研究任务",
      system_prompt: "你负责研究和整理资料。",
      default_model: "mock/schema",
      settings: {},
    });
    expect(await screen.findByText("Queen 会话列表")).toBeInTheDocument();
  });
});
