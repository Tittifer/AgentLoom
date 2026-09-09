import { useMemo, useState, type ReactNode } from "react";

import type { TaskItemRead, TrackerEntryRead, WorkerRead } from "../api/colonies";
import { statusText } from "../utils/format";
import { WorkerMap } from "./WorkerMap";

interface ColonySidebarProps {
  tasks: TaskItemRead[];
  tracker: TrackerEntryRead[];
  workers: WorkerRead[];
  onSelectWorker: (worker: WorkerRead) => void;
  defaultTab?: InspectorTab;
  planContent?: ReactNode;
}

type InspectorTab = "data" | "plan" | "automations" | "workers";

export function ColonySidebar({
  tasks,
  tracker,
  workers,
  onSelectWorker,
  defaultTab = "data",
  planContent,
}: ColonySidebarProps) {
  const [tab, setTab] = useState<InspectorTab>(defaultTab);
  const hasPlanContent = Boolean(planContent);
  const namespaces = useMemo(
    () => Array.from(new Set(tracker.map((entry) => entry.namespace))),
    [tracker],
  );
  const [selectedNamespace, setSelectedNamespace] = useState("");
  const activeNamespace = namespaces.includes(selectedNamespace)
    ? selectedNamespace
    : namespaces[0] ?? "";
  const visibleEntries = tracker.filter((entry) => entry.namespace === activeNamespace);
  const dataColumns = useMemo(
    () => Array.from(new Set(visibleEntries.flatMap((entry) => Object.keys(entry.data)))),
    [visibleEntries],
  );

  return (
    <aside className="workspace-inspector" aria-label="协作详情">
      <div className="inspector-tabs" role="tablist" aria-label="协作详情分类">
        <InspectorTabButton active={tab === "data"} count={tracker.length} label="Data" onClick={() => setTab("data")} />
        <InspectorTabButton active={tab === "plan"} count={tasks.length + (hasPlanContent ? 1 : 0)} label="Plan" onClick={() => setTab("plan")} />
        <InspectorTabButton active={tab === "automations"} label="Automations" onClick={() => setTab("automations")} />
        <InspectorTabButton active={tab === "workers"} count={workers.length} label="Workers" onClick={() => setTab("workers")} />
      </div>

      <div className="inspector-content">
        {tab === "plan" ? (
          <section aria-labelledby="plan-title">
            <span className="section-kicker">执行进度</span>
            <h2 id="plan-title">任务计划</h2>
            {planContent}
            {tasks.length === 0 && !hasPlanContent ? <p className="empty-copy">任务计划会在需要时自动生成。</p> : null}
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
          <section className="data-workspace" aria-labelledby="data-title">
            <h2 className="sr-only" id="data-title">阶段性结果</h2>
            {tracker.length === 0 ? <div className="inspector-empty"><span>▦</span><strong>暂无数据</strong><p>Queen 和 Worker 写入 Tracker 后，结果会显示在这里。</p></div> : null}
            {namespaces.length > 0 ? (
              <div className="data-toolbar" aria-label="Tracker 数据表">
                {namespaces.map((namespace) => (
                  <button
                    className={namespace === activeNamespace ? "active" : ""}
                    key={namespace}
                    onClick={() => setSelectedNamespace(namespace)}
                    type="button"
                  >
                    {displayLabel(namespace)} <span>{tracker.filter((entry) => entry.namespace === namespace).length}</span>
                  </button>
                ))}
              </div>
            ) : null}
            {visibleEntries.length > 0 ? (
              <div className="tracker-table-wrap">
                <table className="tracker-table">
                  <thead><tr><th><span className="primary-key">PK</span> ID</th><th>Status</th>{dataColumns.map((column) => <th key={column}>{displayLabel(column)}</th>)}</tr></thead>
                  <tbody>{visibleEntries.map((entry) => (
                    <tr key={entry.id}>
                      <th scope="row">{displayLabel(entry.entry_key)}</th>
                      <td><span className={`table-status status-${entry.status}`}>{statusText(entry.status)}</span></td>
                      {dataColumns.map((column) => <td key={column}>{readableValue(entry.data[column])}</td>)}
                    </tr>
                  ))}</tbody>
                </table>
                <footer><span>{visibleEntries.length} rows</span><span>Tracker · SQLite</span></footer>
              </div>
            ) : null}
          </section>
        ) : null}

        {tab === "automations" ? (
          <section className="inspector-empty" aria-labelledby="automations-title">
            <span aria-hidden="true">⌁</span>
            <strong id="automations-title">暂无自动化</strong>
            <p>周期任务和自动触发流程会集中显示在这里。</p>
          </section>
        ) : null}

        {tab === "workers" ? (
          <WorkerMap embedded onSelect={onSelectWorker} workers={workers} />
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
  count?: number;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-label={`${tabAccessibleLabel(label)}${count !== undefined ? ` ${count}` : ""}`}
      aria-selected={active}
      className={active ? "active" : ""}
      onClick={onClick}
      role="tab"
      type="button"
    >
      {label}{count !== undefined ? <span>{count}</span> : null}
    </button>
  );
}

function tabAccessibleLabel(label: string): string {
  const labels: Record<string, string> = {
    Data: "数据 Data",
    Plan: "计划 Plan",
    Automations: "自动化 Automations",
    Workers: "Worker Workers",
  };
  return labels[label] ?? label;
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
