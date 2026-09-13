import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import {
  createSession,
  listColonies,
  listSessions,
  type SessionRead,
} from "../../src/api/colonies";
import { listQueens } from "../../src/api/queens";
import { WorkspaceEntryPage } from "../../src/pages/WorkspaceEntryPage";

vi.mock("../../src/api/colonies", () => ({
  createSession: vi.fn(),
  deleteColony: vi.fn(),
  deleteSession: vi.fn(),
  listColonies: vi.fn(),
  listSessions: vi.fn(),
}));
vi.mock("../../src/api/queens", () => ({
  createQueen: vi.fn(),
  listQueens: vi.fn(),
}));

describe("WorkspaceEntryPage", () => {
  it("首页没有独立会话时自动创建并进入会话工作台", async () => {
    const session: SessionRead = {
      layout_version: 2,
      id: "session-1",
      colony_id: null,
      queen_id: "queen-1",
      mode: "dm",
      pending_colony_suggestion: null,
      spawned_colony_id: null,
      superseded_by: null,
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
    vi.mocked(listSessions).mockResolvedValue([]);
    vi.mocked(createSession).mockResolvedValue(session);
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

    expect(await screen.findByText("会话工作区")).toBeInTheDocument();
    expect(vi.mocked(createSession).mock.calls[0]?.[0]).toEqual({ queen_id: "queen-1" });
  });
});
