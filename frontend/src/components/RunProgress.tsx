import type { NodeRunRead, RunRead } from "../api/runs";
import type { LiveRunEvent } from "../hooks/useRunEvents";
import { formatDate, humanize } from "../utils/format";

interface RunProgressProps {
  run: RunRead;
  nodeRuns: NodeRunRead[];
  events?: LiveRunEvent[];
}

function latestAttemptTokenCount(nodeRuns: NodeRunRead[]): number {
  return nodeRuns.reduce((total, nodeRun) => {
    const input = nodeRun.usage?.input_tokens;
    const output = nodeRun.usage?.output_tokens;
    return total + (typeof input === "number" ? input : 0) + (typeof output === "number" ? output : 0);
  }, 0);
}

function tokenCount(nodeRuns: NodeRunRead[], events: LiveRunEvent[]): number {
  const usageEvents = events.filter((event) => event.type === "llm.usage_recorded");
  if (usageEvents.length === 0) {
    return latestAttemptTokenCount(nodeRuns);
  }
  return usageEvents.reduce((total, event) => {
    const input = event.payload.input_tokens;
    const output = event.payload.output_tokens;
    return total + (typeof input === "number" ? input : 0) + (typeof output === "number" ? output : 0);
  }, 0);
}

export function RunProgress({ run, nodeRuns, events = [] }: RunProgressProps) {
  const completed = nodeRuns.filter((nodeRun) => nodeRun.status === "completed").length;
  const percent = nodeRuns.length === 0 ? 0 : Math.round((completed / nodeRuns.length) * 100);

  return (
    <section className="run-progress panel" aria-label="Run progress">
      <div className="run-stat">
        <span>Status</span>
        <strong className={`status-badge status-${run.status}`}>{humanize(run.status)}</strong>
      </div>
      <div className="run-stat">
        <span>Progress</span>
        <strong>{completed} / {nodeRuns.length} nodes</strong>
      </div>
      <div className="run-stat">
        <span>Tokens</span>
        <strong>{tokenCount(nodeRuns, events).toLocaleString()}</strong>
      </div>
      <div className="run-stat">
        <span>Started</span>
        <strong>{formatDate(run.started_at)}</strong>
      </div>
      <div className="progress-track" aria-label={`${percent}% complete`}>
        <span style={{ width: `${percent}%` }} />
      </div>
    </section>
  );
}
