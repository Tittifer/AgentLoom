import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import { cancelRun, getRun, retryRun } from "../api/runs";
import { NodeDetailDrawer } from "../components/NodeDetailDrawer";
import { ResultViewer } from "../components/ResultViewer";
import { RunEventTimeline } from "../components/RunEventTimeline";
import { RunProgress } from "../components/RunProgress";
import { WorkflowGraph } from "../components/WorkflowGraph";
import { useRunEvents } from "../hooks/useRunEvents";
import { formatError } from "../utils/format";

export function RunDetailPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selectedNodeKey, setSelectedNodeKey] = useState<string>();
  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId ?? ""),
    enabled: Boolean(runId),
  });
  const liveEvents = useRunEvents(runId, Boolean(runId));
  const cancelMutation = useMutation({
    mutationFn: () => cancelRun(runId ?? ""),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["run", runId] });
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
  const retryMutation = useMutation({
    mutationFn: () => retryRun(runId ?? ""),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });

  if (!runId) {
    return <div className="panel error-panel"><h2>Invalid run URL</h2></div>;
  }
  if (runQuery.isLoading) {
    return <div className="panel loading-panel">Loading run…</div>;
  }
  if (runQuery.isError || !runQuery.data) {
    return <div className="panel error-panel"><h2>Run could not be loaded</h2><p>{formatError(runQuery.error)}</p></div>;
  }

  const snapshot = runQuery.data;
  const selectedNode = snapshot.workflow.nodes.find((node) => node.key === selectedNodeKey);
  const selectedNodeRun = snapshot.node_runs.find((nodeRun) => nodeRun.node_key === selectedNodeKey);

  return (
    <section aria-labelledby="run-title">
      <Link className="back-link" to={`/tasks/${snapshot.run.task_id}`}>← Back to task</Link>
      <div className="page-heading detail-heading">
        <div>
          <span className="eyebrow">Workflow run</span>
          <h1 id="run-title">Execution</h1>
          <p className="mono-id">{snapshot.run.id}</p>
        </div>
        <div className="heading-actions">
          {snapshot.run.status === "queued" || snapshot.run.status === "running" ? (
            <button
              className="danger-button"
              disabled={cancelMutation.isPending}
              onClick={() => cancelMutation.mutate()}
              type="button"
            >
              {cancelMutation.isPending ? "Cancelling…" : "Cancel run"}
            </button>
          ) : null}
          {snapshot.run.status === "failed" ? (
            <button
              className="primary-button"
              disabled={retryMutation.isPending}
              onClick={() => retryMutation.mutate()}
              type="button"
            >
              {retryMutation.isPending ? "Queuing retry…" : "Retry run"}
            </button>
          ) : null}
        </div>
      </div>

      {cancelMutation.isError || retryMutation.isError ? (
        <div className="form-error" role="alert">
          {formatError(cancelMutation.error ?? retryMutation.error)}
        </div>
      ) : null}

      <RunProgress events={liveEvents.events} nodeRuns={snapshot.node_runs} run={snapshot.run} />
      <div className="run-layout">
        <section className="run-graph-section">
          <div className="panel-heading compact-heading">
            <div>
              <span className="eyebrow">Live DAG</span>
              <h2>Node progress</h2>
            </div>
          </div>
          <WorkflowGraph
            nodeRuns={snapshot.node_runs}
            onSelectNode={setSelectedNodeKey}
            selectedNodeKey={selectedNodeKey}
            workflow={snapshot.workflow}
          />
        </section>
        <RunEventTimeline {...liveEvents} />
      </div>

      <ResultViewer error={snapshot.run.error} result={snapshot.run.result} />

      {selectedNode ? (
        <NodeDetailDrawer
          latestNodeRun={selectedNodeRun}
          node={selectedNode}
          onClose={() => setSelectedNodeKey(undefined)}
          runId={runId}
        />
      ) : null}
    </section>
  );
}
