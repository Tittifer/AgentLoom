import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import { getTask, getTaskWorkflow, planTask, type WorkflowNodeRead } from "../api/tasks";
import { startRun } from "../api/runs";
import { WorkflowGraph } from "../components/WorkflowGraph";
import { formatDate, formatError, formatJson, humanize } from "../utils/format";

const WORKFLOW_STATUSES = new Set(["ready", "running", "completed", "failed", "cancelled"]);

export function TaskDetailPage() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selectedNodeKey, setSelectedNodeKey] = useState<string>();
  const taskQuery = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => getTask(taskId ?? ""),
    enabled: Boolean(taskId),
  });
  const workflowQuery = useQuery({
    queryKey: ["task-workflow", taskId],
    queryFn: () => getTaskWorkflow(taskId ?? ""),
    enabled: Boolean(taskId && taskQuery.data && WORKFLOW_STATUSES.has(taskQuery.data.status)),
  });
  const planMutation = useMutation({
    mutationFn: () => planTask(taskId ?? ""),
    onSuccess: async (workflow) => {
      queryClient.setQueryData(["task-workflow", taskId], workflow);
      await queryClient.invalidateQueries({ queryKey: ["task", taskId] });
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
  const runMutation = useMutation({
    mutationFn: () => startRun(taskId ?? ""),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["task", taskId] });
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  if (!taskId) {
    return <div className="panel error-panel"><h2>Invalid task URL</h2></div>;
  }
  if (taskQuery.isLoading) {
    return <div className="panel loading-panel">Loading task…</div>;
  }
  if (taskQuery.isError || !taskQuery.data) {
    return <div className="panel error-panel"><h2>Task could not be loaded</h2><p>{formatError(taskQuery.error)}</p></div>;
  }

  const task = taskQuery.data;
  const workflow = workflowQuery.data;
  const selectedNode: WorkflowNodeRead | undefined = workflow?.nodes.find(
    (node) => node.key === selectedNodeKey,
  );

  return (
    <section aria-labelledby="task-title">
      <Link className="back-link" to="/tasks">← Back to tasks</Link>
      <div className="page-heading detail-heading">
        <div>
          <span className="eyebrow">Task · {formatDate(task.created_at)}</span>
          <h1 id="task-title">{task.title}</h1>
          <p>{task.goal}</p>
        </div>
        <div className="heading-actions">
          <span className={`status-badge status-${task.status}`}>{humanize(task.status)}</span>
          {task.status === "draft" ? (
            <button className="primary-button" disabled={planMutation.isPending} onClick={() => planMutation.mutate()} type="button">
              {planMutation.isPending ? "Planning…" : "Generate workflow"}
            </button>
          ) : null}
          {task.status === "ready" && workflow ? (
            <button className="primary-button" disabled={runMutation.isPending} onClick={() => runMutation.mutate()} type="button">
              {runMutation.isPending ? "Starting…" : "Start run"}
            </button>
          ) : null}
        </div>
      </div>

      {planMutation.isError || runMutation.isError ? (
        <div className="form-error" role="alert">{formatError(planMutation.error ?? runMutation.error)}</div>
      ) : null}

      <div className="task-meta-grid">
        <section className="panel">
          <span className="eyebrow">Context</span>
          <pre>{formatJson(task.context)}</pre>
        </section>
        <section className="panel definition-summary">
          <span className="eyebrow">Execution limits</span>
          <dl className="definition-list">
            <div><dt>Parallel nodes</dt><dd>{task.max_parallel_nodes}</dd></div>
            <div><dt>Retries per node</dt><dd>{task.max_retries}</dd></div>
          </dl>
        </section>
      </div>

      {task.status === "planning" || workflowQuery.isLoading ? <div className="panel loading-panel">Loading the planned workflow…</div> : null}
      {workflowQuery.isError ? <div className="panel error-panel"><h2>Workflow could not be loaded</h2><p>{formatError(workflowQuery.error)}</p></div> : null}

      {workflow ? (
        <section className="workflow-section">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Workflow v{workflow.version}</span>
              <h2>Agent dependency graph</h2>
              <p>Select a node to inspect its role, tools, and output contract.</p>
            </div>
            <span className="workflow-count">{workflow.nodes.length} nodes</span>
          </div>
          <div className="workflow-layout">
            <WorkflowGraph workflow={workflow} selectedNodeKey={selectedNodeKey} onSelectNode={setSelectedNodeKey} />
            <aside className="panel node-preview">
              {selectedNode ? (
                <>
                  <span className="eyebrow">{selectedNode.role}</span>
                  <h2>{selectedNode.name}</h2>
                  <p>{selectedNode.description}</p>
                  <dl className="definition-list">
                    <div><dt>Depends on</dt><dd>{selectedNode.depends_on.join(", ") || "None"}</dd></div>
                    <div><dt>Tools</dt><dd>{selectedNode.tools.join(", ") || "None"}</dd></div>
                    <div><dt>Review</dt><dd>{selectedNode.review_criteria ?? "Schema validation only"}</dd></div>
                  </dl>
                  <h3>Output schema</h3>
                  <pre>{formatJson(selectedNode.output_schema)}</pre>
                </>
              ) : <p className="muted-placeholder">Select a workflow node to see its details.</p>}
            </aside>
          </div>
        </section>
      ) : null}
    </section>
  );
}
