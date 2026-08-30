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
        <span className="section-kicker">执行进度</span>
        <h2>任务计划</h2>
        {tasks.length === 0 ? <p className="empty-copy">任务计划会在需要时自动生成。</p> : null}
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
        <span className="section-kicker">协作发现</span>
        <h2>阶段性结果</h2>
        {tracker.length === 0 ? <p className="empty-copy">暂时还没有阶段性结果。</p> : null}
        <div className="tracker-list">
          {tracker.map((entry) => (
            <article key={entry.id}>
              <header>
                <strong>{displayLabel(entry.entry_key)}</strong>
                <span>{statusText(entry.status)}</span>
              </header>
              {Object.keys(entry.data).length === 0 ? <p>暂无详细内容</p> : (
                <dl className="tracker-facts">
                  {Object.entries(entry.data).map(([key, value]) => (
                    <div key={key}>
                      <dt>{displayLabel(key)}</dt>
                      <dd>{readableValue(value)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </article>
          ))}
        </div>
      </section>
    </aside>
  );
}

function displayLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function readableValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.map(readableValue).join("、");
  if (typeof value === "object") {
    return Object.entries(value)
      .map(([key, item]) => `${displayLabel(key)}：${readableValue(item)}`)
      .join("；");
  }
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}
