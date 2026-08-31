import { useState } from "react";

import type { SessionRead, TaskItemRead, TrackerEntryRead, WorkerRead } from "../api/colonies";
import { statusText } from "../utils/format";
import { WorkerMap } from "./WorkerMap";

interface ColonySidebarProps {
  tasks: TaskItemRead[];
  tracker: TrackerEntryRead[];
  queen: SessionRead;
  workers: WorkerRead[];
  onSelectWorker: (worker: WorkerRead) => void;
}

type InspectorTab = "plan" | "data" | "workers";

export function ColonySidebar({
  tasks,
  tracker,
  queen,
  workers,
  onSelectWorker,
}: ColonySidebarProps) {
  const [tab, setTab] = useState<InspectorTab>("plan");

  return (
    <aside className="workspace-inspector" aria-label="协作详情">
      <header className="inspector-heading">
        <span className="section-kicker">实时上下文</span>
        <strong>协作详情</strong>
      </header>
      <div className="inspector-tabs" role="tablist" aria-label="协作详情分类">
        <InspectorTabButton active={tab === "plan"} count={tasks.length} label="计划" onClick={() => setTab("plan")} />
        <InspectorTabButton active={tab === "data"} count={tracker.length} label="数据" onClick={() => setTab("data")} />
        <InspectorTabButton active={tab === "workers"} count={workers.length} label="Worker" onClick={() => setTab("workers")} />
      </div>

      <div className="inspector-content">
        {tab === "plan" ? (
          <section aria-labelledby="plan-title">
            <span className="section-kicker">执行进度</span>
            <h2 id="plan-title">任务计划</h2>
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
        ) : null}

        {tab === "data" ? (
          <section aria-labelledby="data-title">
            <span className="section-kicker">协作发现</span>
            <h2 id="data-title">阶段性结果</h2>
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
        ) : null}

        {tab === "workers" ? (
          <WorkerMap embedded onSelect={onSelectWorker} queen={queen} workers={workers} />
        ) : null}
      </div>
    </aside>
  );
}

function InspectorTabButton({
  active,
  count,
  label,
  onClick,
}: {
  active: boolean;
  count: number;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-selected={active}
      className={active ? "active" : ""}
      onClick={onClick}
      role="tab"
      type="button"
    >
      {label}<span>{count}</span>
    </button>
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
