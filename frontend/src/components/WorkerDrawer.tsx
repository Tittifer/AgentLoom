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
            <span className="section-kicker">协作节点详情</span>
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
        <section className="worker-result">
          <h3>工作结果</h3>
          <p>{reportSummary(worker.report)}</p>
        </section>
        {worker.error ? (
          <section className="worker-error">
            <h3>失败原因</h3>
            <p>{errorMessage(worker.error)}</p>
          </section>
        ) : null}
      </aside>
    </div>
  );
}

function reportSummary(report: WorkerRead["report"]): string {
  const summary = report?.summary;
  return typeof summary === "string" && summary.trim() ? summary : "该节点尚未生成可展示的结果。";
}

function errorMessage(error: NonNullable<WorkerRead["error"]>): string {
  const message = error.message;
  return typeof message === "string" && message.trim() ? message : "节点执行失败，请稍后重试。";
}
