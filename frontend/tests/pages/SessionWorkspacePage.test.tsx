import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  dismissColonySuggestion,
  deleteSession,
  forkSessionIntoColony,
  getSession,
  listMessages,
  submitMessage,
  type SessionRead,
} from "../../src/api/colonies";
import { SessionWorkspacePage } from "../../src/pages/SessionWorkspacePage";

vi.mock("../../src/api/colonies", () => ({
  dismissColonySuggestion: vi.fn(),
  deleteSession: vi.fn(),
  forkSessionIntoColony: vi.fn(),
  getSession: vi.fn(),
  listMessages: vi.fn(),
  submitMessage: vi.fn(),
}));
vi.mock("../../src/hooks/useColonyEvents", () => ({ useSessionEvents: () => null }));

const session: SessionRead = {
  id: "session-1",
  colony_id: null,
  queen_id: "queen_general",
  parent_session_id: null,
  actor_type: "queen",
  session_kind: "dm",
  operating_phase: "independent",
  pending_colony_suggestion: {
    id: "suggestion-1",
    suggested_name: "城市对比",
    reason: "六个城市适合并行调研",
    goal: "整理完整横向对比",
    handoff: "保留用户的预算偏好",
    proposed_tasks: ["调研成都", "调研杭州"],
    status: "pending",
    created_at: "2026-09-06T00:00:00Z",
  },
  forked_to_colony_id: null,
  forked_to_session_id: null,
  status: "idle",
  park_reason: null,
  task: {},
  cursor: {},
  budget: {},
  usage: {},
  created_at: "2026-09-06T00:00:00Z",
  updated_at: "2026-09-06T00:00:00Z",
  ended_at: null,
};

describe("SessionWorkspacePage", () => {
  beforeEach(() => {
    vi.mocked(getSession).mockResolvedValue(session);
    vi.mocked(listMessages).mockResolvedValue([]);
    vi.mocked(submitMessage).mockReset();
    vi.mocked(deleteSession).mockReset();
    vi.mocked(dismissColonySuggestion).mockReset();
    vi.mocked(forkSessionIntoColony).mockReset();
  });

  it("仅在用户确认后按 Queen 建议创建 Colony", async () => {
    vi.mocked(forkSessionIntoColony).mockResolvedValue({
      id: "colony-1",
      name: "新城市对比",
      description: "整理完整横向对比",
      queen_id: session.queen_id,
      settings: {},
      status: "active",
      model: "mock/test",
      queen_session_id: "colony-session-1",
      source_session_id: session.id,
      created_at: session.created_at,
      updated_at: session.updated_at,
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/sessions/session-1"]}>
          <Routes>
            <Route path="/sessions/:sessionId" element={<SessionWorkspacePage />} />
            <Route path="/colonies/:colonyId" element={<div>Colony 工作区</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("六个城市适合并行调研")).toBeInTheDocument();
    expect(forkSessionIntoColony).not.toHaveBeenCalled();
    const name = screen.getByLabelText("Colony 名称");
    await userEvent.clear(name);
    await userEvent.type(name, "新城市对比");
    await userEvent.click(screen.getByRole("button", { name: "确认创建 Colony" }));

    expect(forkSessionIntoColony).toHaveBeenCalledWith("session-1", {
      suggestion_id: "suggestion-1",
      name: "新城市对比",
      description: "整理完整横向对比",
    });
    expect(await screen.findByText("Colony 工作区")).toBeInTheDocument();
  });

  it("确认后删除独立会话", async () => {
    vi.mocked(deleteSession).mockResolvedValue();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/sessions/session-1"]}>
          <Routes>
            <Route path="/sessions/:sessionId" element={<SessionWorkspacePage />} />
            <Route path="/queens/:queenId" element={<div>会话已删除</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByRole("button", { name: "删除" }));

    expect(deleteSession).toHaveBeenCalledWith("session-1");
    expect(await screen.findByText("会话已删除")).toBeInTheDocument();
  });
});
