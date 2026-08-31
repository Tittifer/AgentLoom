import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { ColonyRead } from "../../src/api/colonies";
import { SessionNavigation } from "../../src/components/SessionNavigation";

const colony: ColonyRead = {
  id: "colony-1",
  name: "城市对比",
  description: "",
  queen_profile: "general",
  model: "mock/schema",
  settings: {},
  status: "active",
  queen_session_id: "queen-1",
  created_at: "2026-08-30T00:00:00Z",
  updated_at: "2026-08-30T00:00:00Z",
};

describe("SessionNavigation", () => {
  it("展示会话并支持新建与收起", async () => {
    const onCreate = vi.fn();
    render(
      <MemoryRouter initialEntries={["/colonies/colony-1"]}>
        <SessionNavigation colonies={[colony]} creating={false} onCreate={onCreate} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: /城市对比/ })).toHaveClass("active");
    await userEvent.click(screen.getByRole("button", { name: "新建会话" }));
    expect(onCreate).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button", { name: "收起会话导航" }));
    expect(screen.getByRole("button", { name: "展开会话导航" })).toBeInTheDocument();
  });
});
