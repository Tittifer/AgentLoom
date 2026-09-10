import type { WorkerRead } from "../api/colonies";
import { statusText } from "../utils/format";
import { MarkdownContent } from "./MarkdownContent";

interface WorkerCardProps {
  worker: WorkerRead;
  reportContent?: string;
  compact?: boolean;
  onSelect?: (worker: WorkerRead) => void;
}

export function WorkerCard({ worker, reportContent, compact = false, onSelect }: WorkerCardProps) {
  const content = reportContent?.trim() || workerResult(worker);
  return (
    <article className={`hive-worker-card status-ring-${worker.status}${compact ? " is-compact" : ""}`}>
      <span className="hive-worker-icon" aria-hidden="true">⌘</span>
      <div className="hive-worker-body">
        <span className="hive-worker-header">
          <strong>Worker</strong>
          <code>{worker.id.slice(0, 8)}</code>
          <span className={`hive-worker-status status-${worker.status}`}>
            <i aria-hidden="true" />
            {statusText(worker.status)}
          </span>
          <small>{workerDuration(worker)}</small>
        </span>
        <div className="hive-worker-surface">
          <strong className="hive-worker-task">{worker.task || "未命名任务"}</strong>
          <span className="hive-worker-meta">独立 AgentLoop · {worker.timeout_seconds} 秒软超时</span>
          <div className="hive-worker-report">
            <MarkdownContent content={content} />
          </div>
        </div>
      </div>
      {onSelect ? (
        <button
          aria-label={`查看 Worker ${worker.task}`}
          className="hive-worker-hit-area"
          onClick={() => onSelect(worker)}
          type="button"
        />
      ) : null}
    </article>
  );
}

function workerResult(worker: WorkerRead): string {
  const summary = worker.report?.summary;
  if (typeof summary === "string" && summary.trim()) return summary;

  const error = worker.error?.message;
  if (typeof error === "string" && error.trim()) return error;

  const fallback: Record<WorkerRead["status"], string> = {
    queued: "等待 Queen 分派执行。",
    running: "正在独立执行任务…",
    reporting: "正在整理结果并向 Queen 汇报…",
    completed: "Worker 已完成任务。",
    partial: "Worker 已返回部分结果。",
    failed: "Worker 执行失败。",
    timed_out: "Worker 执行超时。",
    cancelled: "Worker 已停止执行。",
  };
  return fallback[worker.status];
}

function workerDuration(worker: WorkerRead): string {
  if (!worker.started_at) return "等待启动";
  if (!worker.ended_at) return "执行中";
  const milliseconds = Date.parse(worker.ended_at) - Date.parse(worker.started_at);
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return "已结束";
  const seconds = Math.max(1, Math.round(milliseconds / 1000));
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}
