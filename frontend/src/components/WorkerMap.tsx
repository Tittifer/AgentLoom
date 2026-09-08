import type { WorkerRead } from "../api/colonies";
import { WorkerCard } from "./WorkerCard";

interface WorkerMapProps {
  workers: WorkerRead[];
  onSelect: (worker: WorkerRead) => void;
  embedded?: boolean;
}

export function WorkerMap({ workers, onSelect, embedded = false }: WorkerMapProps) {
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
          <span className="section-kicker">协作执行</span>
          <h2 id="worker-map-title">Workers</h2>
          <p>每个 Worker 使用独立 AgentLoop 并行执行，完成后向 Queen 汇报。</p>
        </div>
        <div className="map-summary" aria-label="节点统计">
          <span><b>{workers.length}</b> 全部</span>
          <span><b>{activeCount}</b> 进行中</span>
          <span><b>{completedCount}</b> 已完成</span>
        </div>
      </header>

      {workers.length === 0 ? (
        <div className="map-placeholder">
          <strong>暂无 Worker</strong>
          <p>Queen 分派并行任务后，Worker 会出现在对话时间线和这里。</p>
        </div>
      ) : null}
      <div className="hive-worker-list">
        {workers.map((worker) => (
          <WorkerCard compact key={worker.id} onSelect={onSelect} worker={worker} />
        ))}
      </div>
    </section>
  );
}
