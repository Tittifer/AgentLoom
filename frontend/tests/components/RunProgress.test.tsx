import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { NodeRunRead, RunRead } from "../../src/api/runs";
import { RunProgress } from "../../src/components/RunProgress";

const run: RunRead = {
  id: "run-1",
  task_id: "task-1",
  workflow_id: "workflow-1",
  status: "running",
  input: {},
  result: null,
  error: null,
  created_at: "2026-08-26T00:00:00Z",
  started_at: "2026-08-26T00:00:01Z",
  ended_at: null,
};

function node(status: NodeRunRead["status"], usage: NodeRunRead["usage"]): NodeRunRead {
  return {
    id: `${status}-node`,
    run_id: run.id,
    node_key: `${status}_node`,
    status,
    attempt: 1,
    input: {},
    output: null,
    review: null,
    usage,
    error: null,
    created_at: run.created_at,
    started_at: run.started_at,
    ended_at: null,
  };
}

describe("RunProgress", () => {
  it("renders node completion and token totals", () => {
    render(
      <RunProgress
        nodeRuns={[
          node("completed", { input_tokens: 10, output_tokens: 5 }),
          node("running", null),
        ]}
        run={run}
      />,
    );

    expect(screen.getByText("1 / 2 nodes")).toBeInTheDocument();
    expect(screen.getByText("15")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
  });
});
