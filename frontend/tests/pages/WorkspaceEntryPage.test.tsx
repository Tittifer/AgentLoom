import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { listColonies, type SessionRead } from "../../src/api/colonies";
import { createQueenSession, listQueens, listQueenSessions } from "../../src/api/queens";
import { WorkspaceEntryPage } from "../../src/pages/WorkspaceEntryPage";

vi.mock("../../src/api/colonies", () => ({
  deleteColony: vi.fn(),
  deleteSession: vi.fn(),
  listColonies: vi.fn(),
}));
vi.mock("../../src/api/queens", () => ({
  createQueen: vi.fn(),
  createQueenSession: vi.fn(),
  listQueens: vi.fn(),
  listQueenSessions: vi.fn(),
}));

describe("WorkspaceEntryPage", () => {
  it("通过侧栏选择 Queen 并直接进入会话", async () => {
    const session: SessionRead = {
      id: "session-1",
      colony_id: null,
      queen_id: "queen-1",
      parent_session_id: null,
      actor_type: "queen",
      session_kind: "dm",
      operating_phase: "independent",
      pending_colony_suggestion: null,
      forked_to_colony_id: null,
      forked_to_session_id: null,
      status: "idle",
      park_reason: null,
      task: {},
      cursor: {},
      budget: {},
      usage: {},
      created_at: "2026-09-08T00:00:00Z",
      updated_at: "2026-09-08T00:00:00Z",
      ended_at: null,
    };
    vi.mocked(listQueens).mockResolvedValue([{
      id: "queen-1",
      name: "Research",
      description: "研究助手",
      system_prompt: "",
      created_at: session.created_at,
      updated_at: session.updated_at,
    }]);
    vi.mocked(listColonies).mockResolvedValue([]);
    vi.mocked(listQueenSessions).mockResolvedValue([]);
    vi.mocked(createQueenSession).mockResolvedValue(session);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route path="/" element={<WorkspaceEntryPage />} />
            <Route path="/sessions/:sessionId" element={<div>会话工作区</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByRole("heading", { name: "选择一个 Queen" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新建会话" })).toBeDisabled();
    await userEvent.click(await screen.findByRole("button", { name: /Research/ }));

    expect(createQueenSession).toHaveBeenCalledWith("queen-1");
    expect(await screen.findByText("会话工作区")).toBeInTheDocument();
  });
});
