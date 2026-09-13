import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createSession,
  deleteColony,
  deleteSession,
  listColonies,
  listSessions,
  type ColonyRead,
  type SessionRead,
} from "../../src/api/colonies";
import { listQueens } from "../../src/api/queens";
import { SessionNavigation } from "../../src/components/SessionNavigation";

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

const session: SessionRead = {
  layout_version: 2,
  id: "session-1",
  colony_id: null,
  queen_id: "queen_general",
  mode: "dm",
  pending_colony_suggestion: null,
  spawned_colony_id: null,
  superseded_by: null,
  status: "idle",
  park_reason: null,
  task: { title: "城市规划" },
  cursor: {},
  budget: {},
  usage: {},
  created_at: "2026-08-30T00:00:00Z",
  updated_at: "2026-08-30T00:00:00Z",
  ended_at: null,
};

const colony: ColonyRead = {
  layout_version: 2,
  id: "colony-1",
  name: "城市对比",
  description: "",
  queen_id: "queen_general",
  model: "gpt-5",
  settings: {},
  status: "active",
  source_session_id: null,
  created_at: "2026-08-30T00:00:00Z",
  updated_at: "2026-08-30T00:00:00Z",
};

describe("SessionNavigation", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.mocked(listQueens).mockResolvedValue([
      {
        id: "queen_general",
        name: "General",
        description: "通用 Queen",
        system_prompt: "",
        created_at: "2026-08-30T00:00:00Z",
        updated_at: "2026-08-30T00:00:00Z",
      },
    ]);
    vi.mocked(listSessions).mockResolvedValue([session]);
    vi.mocked(listColonies).mockResolvedValue([colony]);
    vi.mocked(createSession).mockReset();
    vi.mocked(deleteSession).mockReset();
    vi.mocked(deleteColony).mockReset();
  });

  it("在侧栏展示资源并直接创建会话", async () => {
    vi.mocked(createSession).mockResolvedValue({ ...session, id: "session-2" });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/sessions/session-1"]}>
          <Routes>
            <Route
              path="/sessions/:sessionId"
              element={<SessionNavigation currentSessionId="session-1" queenId="queen_general" />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("link", { name: /城市规划/ })).toHaveClass("active");
    expect(screen.getByRole("link", { name: /城市对比/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /General/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "记忆" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "设置" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "新建会话" }));
    expect(vi.mocked(createSession).mock.calls[0]?.[0]).toEqual({ queen_id: "queen_general" });

    await userEvent.click(screen.getByRole("button", { name: "收起会话导航" }));
    expect(screen.getByRole("button", { name: "展开会话导航" })).toBeInTheDocument();
  });

  it("在侧栏确认后删除当前会话", async () => {
    vi.mocked(deleteSession).mockResolvedValue();
    vi.mocked(deleteColony).mockResolvedValue();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/sessions/session-1"]}>
          <Routes>
            <Route
              path="/sessions/:sessionId"
              element={<SessionNavigation currentSessionId="session-1" queenId="queen_general" />}
            />
            <Route path="/" element={<div>工作区首页</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByRole("button", { name: "删除会话 城市规划" }));
    await waitFor(() => expect(vi.mocked(deleteSession).mock.calls[0]?.[0]).toBe("session-1"));
    expect(await screen.findByText("工作区首页")).toBeInTheDocument();
  });

  it("在侧栏确认后删除当前 Colony", async () => {
    vi.mocked(deleteColony).mockResolvedValue();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/colonies/colony-1"]}>
          <Routes>
            <Route
              path="/colonies/:colonyId"
              element={<SessionNavigation queenId="queen_general" />}
            />
            <Route path="/" element={<div>工作区首页</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByRole("button", { name: "删除 Colony 城市对比" }));
    await waitFor(() => expect(vi.mocked(deleteColony).mock.calls[0]?.[0]).toBe("colony-1"));
    expect(await screen.findByText("工作区首页")).toBeInTheDocument();
  });
});
