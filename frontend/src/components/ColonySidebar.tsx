import type { TaskItemRead, TrackerEntryRead } from "../api/colonies";
import { statusText } from "../utils/format";

interface ColonySidebarProps {
  tasks: TaskItemRead[];
  tracker: TrackerEntryRead[];
}

export function ColonySidebar({ tasks, tracker }: ColonySidebarProps) {
  return (
    <aside className="colony-sidebar">
      <section className="workspace-panel compact-panel">
        <span className="section-kicker">TASK PLAN</span>
        <h2>任务计划</h2>
        {tasks.length === 0 ? <p className="empty-copy">Queen 尚未创建任务项。</p> : null}
        <ol className="task-plan-list">
          {tasks.map((task) => (
            <li key={task.id}>
              <span className={`task-check task-${task.status}`} aria-hidden="true" />
              <div>
                <strong>{task.title}</strong>
                <small>{statusText(task.status)}</small>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="workspace-panel compact-panel">
        <span className="section-kicker">SHARED TRACKER</span>
        <h2>共享状态</h2>
        {tracker.length === 0 ? <p className="empty-copy">暂无 Worker 写入的结构化发现。</p> : null}
        <div className="tracker-list">
          {tracker.map((entry) => (
            <article key={entry.id}>
              <header>
                <strong>{entry.entry_key}</strong>
                <span>v{entry.version}</span>
              </header>
              <small>{entry.namespace} · {statusText(entry.status)}</small>
              <pre>{JSON.stringify(entry.data, null, 2)}</pre>
            </article>
          ))}
        </div>
      </section>
    </aside>
  );
}
