import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { NewTaskPage } from "../../src/pages/NewTaskPage";

const task = {
  id: "task-1",
  title: "Research phones",
  goal: "Compare three phones",
  context: {},
  max_parallel_nodes: 3,
  max_retries: 2,
  status: "draft",
  created_at: "2026-08-26T00:00:00Z",
};

afterEach(() => vi.unstubAllGlobals());

describe("NewTaskPage", () => {
  it("creates, plans, and navigates to the task", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(task), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "workflow-1" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/tasks/new"]}>
          <Routes>
            <Route path="/tasks/new" element={<NewTaskPage />} />
            <Route path="/tasks/:taskId" element={<div>Task destination</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.type(screen.getByLabelText("Title"), task.title);
    await user.type(screen.getByLabelText("Goal"), task.goal);
    fireEvent.change(screen.getByLabelText("Context (JSON object)"), {
      target: { value: '{"language":"en"}' },
    });
    await user.click(screen.getByRole("button", { name: "Create and plan" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/tasks");
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/tasks/task-1/plan");
    expect(await screen.findByText("Task destination")).toBeInTheDocument();
  });

  it("rejects context that is not a JSON object", async () => {
    const queryClient = new QueryClient();
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <NewTaskPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.type(screen.getByLabelText("Title"), task.title);
    await user.type(screen.getByLabelText("Goal"), task.goal);
    fireEvent.change(screen.getByLabelText("Context (JSON object)"), {
      target: { value: "[]" },
    });
    await user.click(screen.getByRole("button", { name: "Create and plan" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Context must be a JSON object.");
  });
});
