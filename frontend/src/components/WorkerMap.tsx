import type { SessionRead, WorkerRead } from "../api/colonies";
import { statusText } from "../utils/format";

interface WorkerMapProps {
  queen: SessionRead;
  workers: WorkerRead[];
  onSelect: (worker: WorkerRead) => void;
  embedded?: boolean;
}

export function WorkerMap({ queen, workers, onSelect, embedded = false }: WorkerMapProps) {
  const activeCount = workers.filter((worker) =>
    ["queued", "running", "reporting"].includes(worker.status)
  ).length;
  const completedCount = workers.filter((worker) =>
    ["completed", "partial"].includes(worker.status)
  ).length;

  return (
    <section
      className={`${embedded ? "embedded-worker-map" : "workspace-panel"} worker-map-panel`}
      aria-labelledby="worker-map-title"
    >
      <header className="panel-title-row">
        <div>
          <span className="section-kicker">协作视图</span>
          <h2 id="worker-map-title">智能体任务图</h2>
          <p>主智能体负责理解目标，并把可并行的工作分配给协作节点。</p>
        </div>
        <div className="map-summary" aria-label="节点统计">
          <span><b>{workers.length}</b> 全部</span>
          <span><b>{activeCount}</b> 进行中</span>
          <span><b>{completedCount}</b> 已完成</span>
        </div>
      </header>

      <div className="colony-map">
        <div className={`queen-node status-ring-${queen.status}`}>
          <span className="node-avatar">主</span>
          <div>
            <small>主智能体</small>
            <strong>任务协调者</strong>
            <em>{statusText(queen.status)}</em>
          </div>
        </div>
        <div className="worker-node-grid">
          {workers.length === 0 ? (
            <div className="map-placeholder">
              <strong>当前由主智能体处理</strong>
              <p>任务需要拆分时，新的协作节点会自动出现在这里。</p>
            </div>
          ) : null}
          {workers.map((worker, index) => (
            <button
              className={`worker-node status-ring-${worker.status}`}
              key={worker.id}
              onClick={() => onSelect(worker)}
              title={worker.task}
              type="button"
            >
              <span className="node-avatar">{index + 1}</span>
              <span className="worker-node-copy">
                <small>协作节点 {index + 1}</small>
                <strong>{trimTask(worker.task)}</strong>
                <em><i aria-hidden="true" />{statusText(worker.status)}</em>
              </span>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

function trimTask(task: string) {
  return task.length > 42 ? `${task.slice(0, 42)}…` : task;
}
