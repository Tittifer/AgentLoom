import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NodeRunRead } from "../../src/api/runs";
import type { WorkflowRead } from "../../src/api/tasks";
import { WorkflowGraph } from "../../src/components/WorkflowGraph";

afterEach(cleanup);

const workflow: WorkflowRead = {
  id: "workflow-1",
  task_id: "task-1",
  version: 1,
  status: "ready",
  final_node: "report",
  created_at: "2026-08-29T00:00:00Z",
  nodes: [
    {
      id: "node-1",
      key: "research",
      name: "收集资料",
      role: "researcher",
      description: "查找并整理资料",
      system_prompt: "研究",
      depends_on: [],
      tools: ["web_search"],
      output_schema: {},
      review_criteria: null,
      sort_order: 0,
    },
    {
      id: "node-2",
      key: "report",
      name: "生成报告",
      role: "writer",
      description: "汇总研究结果",
      system_prompt: "写作",
      depends_on: ["research"],
      tools: [],
      output_schema: {},
      review_criteria: null,
      sort_order: 1,
    },
  ],
  edges: [
    {
      id: "edge-1",
      source_node_key: "research",
      target_node_key: "report",
    },
  ],
};

function nodeRun(
  nodeKey: string,
  status: NodeRunRead["status"],
  attempt = 1,
): NodeRunRead {
  return {
    id: `${nodeKey}-${attempt}`,
    run_id: "run-1",
    node_key: nodeKey,
    status,
    attempt,
    input: {},
    output: null,
    review: null,
    usage: null,
    error: null,
    created_at: "2026-08-29T00:00:00Z",
    started_at: null,
    ended_at: null,
  };
}

describe("WorkflowGraph", () => {
  it("shows node state, progress summary and final-output context", () => {
    render(
      <WorkflowGraph
        nodeRuns={[nodeRun("research", "completed"), nodeRun("report", "running", 2)]}
        onSelectNode={() => undefined}
        workflow={workflow}
      />,
    );

    expect(screen.getByText("收集资料")).toBeInTheDocument();
    expect(screen.getByText("生成报告")).toBeInTheDocument();
    expect(screen.getByText("最终输出")).toBeInTheDocument();
    expect(screen.getByText("第 2 次尝试")).toBeInTheDocument();
    expect(screen.getByText("1", { selector: ".summary-completed strong" })).toBeInTheDocument();
    expect(screen.getByText("1", { selector: ".summary-active strong" })).toBeInTheDocument();
  });

  it("opens node details when a node is selected", () => {
    const onSelectNode = vi.fn();
    render(<WorkflowGraph onSelectNode={onSelectNode} workflow={workflow} />);

    fireEvent.click(screen.getByText("收集资料"));

    expect(onSelectNode).toHaveBeenCalledWith("research");
  });
});
