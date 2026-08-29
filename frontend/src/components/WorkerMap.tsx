import type { SessionRead, WorkerRead } from "../api/colonies";
import { statusText } from "../utils/format";

interface WorkerMapProps {
  queen: SessionRead;
  workers: WorkerRead[];
  onSelect: (worker: WorkerRead) => void;
}

export function WorkerMap({ queen, workers, onSelect }: WorkerMapProps) {
  return (
    <section className="workspace-panel worker-map-panel" aria-labelledby="worker-map-title">
      <header className="panel-title-row">
        <div>
          <span className="section-kicker">COLONY 拓扑</span>
          <h2 id="worker-map-title">动态智能体</h2>
        </div>
        <span className="count-chip">{workers.length} 个 Worker</span>
      </header>

      <div className="colony-map">
        <div className={`queen-node status-ring-${queen.status}`}>
          <span>Q</span>
          <strong>Queen</strong>
          <small>{statusText(queen.status)}</small>
        </div>
        <div className="worker-node-grid">
          {workers.length === 0 ? (
            <p className="map-placeholder">Queen 尚未派生 Worker</p>
          ) : null}
          {workers.map((worker, index) => (
            <button
              className={`worker-node status-ring-${worker.status}`}
              key={worker.id}
              onClick={() => onSelect(worker)}
              title={worker.task}
              type="button"
            >
              <span>W{index + 1}</span>
              <strong>{trimTask(worker.task)}</strong>
              <small>{statusText(worker.status)}</small>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

function trimTask(task: string) {
  return task.length > 18 ? `${task.slice(0, 18)}…` : task;
}
