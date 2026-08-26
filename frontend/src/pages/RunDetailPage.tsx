import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { getRun } from "../api/runs";
import { NodeDetailDrawer } from "../components/NodeDetailDrawer";
import { ResultViewer } from "../components/ResultViewer";
import { RunEventTimeline } from "../components/RunEventTimeline";
import { RunProgress } from "../components/RunProgress";
import { WorkflowGraph } from "../components/WorkflowGraph";
import { useRunEvents } from "../hooks/useRunEvents";
import { formatError } from "../utils/format";

export function RunDetailPage() {
  const { runId } = useParams();
  const [selectedNodeKey, setSelectedNodeKey] = useState<string>();
  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId ?? ""),
    enabled: Boolean(runId),
  });
  const liveEvents = useRunEvents(runId, Boolean(runId));

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
      </div>

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
