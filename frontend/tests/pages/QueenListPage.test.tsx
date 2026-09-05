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
  id: "queen_general",
  name: "General",
  description: "通用 Queen",
  system_prompt: "负责协调任务。",
  model: "gpt-5",
  protocol: "openai",
  base_url: "https://api.openai.com",
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
      id: "queen_research",
      name: "研究 Queen",
      description: "负责研究任务",
      system_prompt: "你负责研究和整理资料。",
      model: "claude-sonnet-4",
      protocol: "claude",
      base_url: "https://api.anthropic.com",
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

    expect(await screen.findByText("General")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "新建 Queen" }));
    await userEvent.type(screen.getByLabelText("名称"), "研究 Queen");
    await userEvent.type(screen.getByLabelText("描述"), "负责研究任务");
    await userEvent.type(screen.getByLabelText("系统提示词"), "你负责研究和整理资料。");
    await userEvent.type(screen.getByLabelText(/模型名称/), "claude-sonnet-4");
    await userEvent.type(screen.getByLabelText(/服务 Base URL/), "https://api.anthropic.com");
    await userEvent.type(screen.getByLabelText(/API Key/), "secret-key");
    await userEvent.click(screen.getByRole("button", { name: "创建 Queen" }));

    expect(vi.mocked(createQueen).mock.calls[0]?.[0]).toEqual({
      name: "研究 Queen",
      description: "负责研究任务",
      system_prompt: "你负责研究和整理资料。",
      model: "claude-sonnet-4",
      base_url: "https://api.anthropic.com",
      api_key: "secret-key",
      settings: {},
    });
    expect(await screen.findByText("Queen 会话列表")).toBeInTheDocument();
  });
});
