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
    <section className="run-progress panel" aria-label="运行进度">
      <div className="run-stat">
        <span>状态</span>
        <strong className={`status-badge status-${run.status}`}>{humanize(run.status)}</strong>
      </div>
      <div className="run-stat">
        <span>进度</span>
        <strong>{completed} / {nodeRuns.length} 个节点</strong>
      </div>
      <div className="run-stat">
        <span>Token 用量</span>
        <strong>{tokenCount(nodeRuns, events).toLocaleString()}</strong>
      </div>
      <div className="run-stat">
        <span>开始时间</span>
        <strong>{formatDate(run.started_at)}</strong>
      </div>
      <div className="progress-track" aria-label={`已完成 ${percent}%`}>
        <span style={{ width: `${percent}%` }} />
      </div>
    </section>
  );
}
