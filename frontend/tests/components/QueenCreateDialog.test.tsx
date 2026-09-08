import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createQueen, type QueenRead } from "../../src/api/queens";
import { QueenCreateDialog } from "../../src/components/QueenCreateDialog";

vi.mock("../../src/api/queens", () => ({ createQueen: vi.fn() }));

const queen: QueenRead = {
  id: "queen_research",
  name: "研究 Queen",
  description: "负责研究",
  system_prompt: "整理研究资料。",
  created_at: "2026-09-08T00:00:00Z",
  updated_at: "2026-09-08T00:00:00Z",
};

describe("QueenCreateDialog", () => {
  beforeEach(() => vi.mocked(createQueen).mockReset());
  afterEach(cleanup);

  it("在弹窗中创建 Queen 并关闭弹窗", async () => {
    vi.mocked(createQueen).mockResolvedValue(queen);
    const onClose = vi.fn();
    const onCreated = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <QueenCreateDialog onClose={onClose} onCreated={onCreated} open />
      </QueryClientProvider>,
    );

    await userEvent.type(screen.getByLabelText("名称"), queen.name);
    await userEvent.type(screen.getByLabelText("描述"), queen.description);
    await userEvent.type(screen.getByLabelText("系统提示词"), queen.system_prompt);
    await userEvent.click(screen.getByRole("button", { name: "创建 Queen" }));

    expect(vi.mocked(createQueen).mock.calls[0]?.[0]).toEqual({
      name: queen.name,
      description: queen.description,
      system_prompt: queen.system_prompt,
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onCreated).toHaveBeenCalledWith(queen);
  });
});
