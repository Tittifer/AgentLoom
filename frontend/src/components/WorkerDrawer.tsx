import type { WorkerRead } from "../api/colonies";
import { formatDateTime, statusText } from "../utils/format";

interface WorkerDrawerProps {
  worker: WorkerRead | null;
  onClose: () => void;
}

export function WorkerDrawer({ worker, onClose }: WorkerDrawerProps) {
  if (!worker) return null;
  return (
    <div className="drawer-backdrop" onClick={onClose} role="presentation">
      <aside className="worker-drawer" onClick={(event) => event.stopPropagation()}>
        <header className="panel-title-row">
          <div>
            <span className="section-kicker">WORKER 详情</span>
            <h2>{worker.task}</h2>
          </div>
          <button aria-label="关闭" className="icon-button" onClick={onClose} type="button">×</button>
        </header>
        <dl className="worker-details">
          <div><dt>状态</dt><dd>{statusText(worker.status)}</dd></div>
          <div><dt>超时</dt><dd>{worker.timeout_seconds} 秒</dd></div>
          <div><dt>开始</dt><dd>{formatDateTime(worker.started_at)}</dd></div>
          <div><dt>结束</dt><dd>{formatDateTime(worker.ended_at)}</dd></div>
        </dl>
        <h3>输入</h3>
        <pre>{JSON.stringify(worker.input, null, 2)}</pre>
        <h3>汇报</h3>
        <pre>{worker.report ? JSON.stringify(worker.report, null, 2) : "尚未汇报"}</pre>
        {worker.error ? <><h3>错误</h3><pre>{JSON.stringify(worker.error, null, 2)}</pre></> : null}
      </aside>
    </div>
  );
}
