import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getMemory, listMemories, updateMemory, type Memory } from "../../src/api/memories";
import { listQueens } from "../../src/api/queens";
import { MemoryLibraryPage } from "../../src/pages/MemoryLibraryPage";

vi.mock("../../src/api/memories", () => ({
  deleteMemory: vi.fn(),
  getMemory: vi.fn(),
  listMemories: vi.fn(),
  updateMemory: vi.fn(),
}));
vi.mock("../../src/api/queens", () => ({ listQueens: vi.fn() }));

const memory: Memory = {
  path: "global/style.md",
  filename: "style.md",
  scope: "global",
  queen_id: null,
  name: "回复风格",
  description: "用户偏好的回复形式",
  type: "preference",
  mtime: 1,
  content: null,
};

describe("MemoryLibraryPage", () => {
  beforeEach(() => {
    vi.mocked(listMemories).mockResolvedValue([memory]);
    vi.mocked(listQueens).mockResolvedValue([]);
    vi.mocked(getMemory).mockResolvedValue({ ...memory, content: "原内容\n" });
    vi.mocked(updateMemory).mockResolvedValue({ ...memory, content: "新内容" });
  });

  it("读取并更新一条长期记忆", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryLibraryPage /></QueryClientProvider>);

    await userEvent.click(await screen.findByRole("button", { name: /回复风格/ }));
    const editor = await screen.findByRole("textbox", { name: "记忆内容" });
    await userEvent.clear(editor);
    await userEvent.type(editor, "新内容");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(updateMemory).toHaveBeenCalledWith("global/style.md", "新内容");
  });
});
