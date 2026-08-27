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
    return <div className="panel error-panel"><h2>任务地址无效</h2></div>;
  }
  if (taskQuery.isLoading) {
    return <div className="panel loading-panel">正在加载任务…</div>;
  }
  if (taskQuery.isError || !taskQuery.data) {
    return <div className="panel error-panel"><h2>无法加载任务</h2><p>{formatError(taskQuery.error)}</p></div>;
  }

  const task = taskQuery.data;
  const workflow = workflowQuery.data;
  const selectedNode: WorkflowNodeRead | undefined = workflow?.nodes.find(
    (node) => node.key === selectedNodeKey,
  );

  return (
    <section aria-labelledby="task-title">
      <Link className="back-link" to="/tasks">← 返回任务列表</Link>
      <div className="page-heading detail-heading">
        <div>
          <span className="eyebrow">任务 · {formatDate(task.created_at)}</span>
          <h1 id="task-title">{task.title}</h1>
          <p>{task.goal}</p>
        </div>
        <div className="heading-actions">
          <span className={`status-badge status-${task.status}`}>{humanize(task.status)}</span>
          {task.status === "draft" ? (
            <button className="primary-button" disabled={planMutation.isPending} onClick={() => planMutation.mutate()} type="button">
              {planMutation.isPending ? "正在规划…" : "生成工作流"}
            </button>
          ) : null}
          {task.status === "ready" && workflow ? (
            <button className="primary-button" disabled={runMutation.isPending} onClick={() => runMutation.mutate()} type="button">
              {runMutation.isPending ? "正在启动…" : "启动运行"}
            </button>
          ) : null}
        </div>
      </div>

      {planMutation.isError || runMutation.isError ? (
        <div className="form-error" role="alert">{formatError(planMutation.error ?? runMutation.error)}</div>
      ) : null}

      <div className="task-meta-grid">
        <section className="panel">
          <span className="eyebrow">上下文</span>
          <pre>{formatJson(task.context)}</pre>
        </section>
        <section className="panel definition-summary">
          <span className="eyebrow">执行限制</span>
          <dl className="definition-list">
            <div><dt>并行节点数</dt><dd>{task.max_parallel_nodes}</dd></div>
            <div><dt>单节点重试次数</dt><dd>{task.max_retries}</dd></div>
          </dl>
        </section>
      </div>

      {task.status === "planning" || workflowQuery.isLoading ? <div className="panel loading-panel">正在加载规划后的工作流…</div> : null}
      {workflowQuery.isError ? <div className="panel error-panel"><h2>无法加载工作流</h2><p>{formatError(workflowQuery.error)}</p></div> : null}

      {workflow ? (
        <section className="workflow-section">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">工作流 v{workflow.version}</span>
              <h2>智能体依赖图</h2>
              <p>选择节点以查看其角色、工具和输出约定。</p>
            </div>
            <span className="workflow-count">{workflow.nodes.length} 个节点</span>
          </div>
          <div className="workflow-layout">
            <WorkflowGraph workflow={workflow} selectedNodeKey={selectedNodeKey} onSelectNode={setSelectedNodeKey} />
            <aside className="panel node-preview">
              {selectedNode ? (
                <>
                  <span className="eyebrow">{humanize(selectedNode.role)}</span>
                  <h2>{selectedNode.name}</h2>
                  <p>{selectedNode.description}</p>
                  <dl className="definition-list">
                    <div><dt>依赖节点</dt><dd>{selectedNode.depends_on.join(", ") || "无"}</dd></div>
                    <div><dt>工具</dt><dd>{selectedNode.tools.join(", ") || "无"}</dd></div>
                    <div><dt>审核标准</dt><dd>{selectedNode.review_criteria ?? "仅进行 Schema 校验"}</dd></div>
                  </dl>
                  <h3>输出 Schema</h3>
                  <pre>{formatJson(selectedNode.output_schema)}</pre>
                </>
              ) : <p className="muted-placeholder">选择一个工作流节点以查看详情。</p>}
            </aside>
          </div>
        </section>
      ) : null}
    </section>
  );
}
