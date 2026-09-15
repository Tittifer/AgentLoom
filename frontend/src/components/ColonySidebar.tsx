import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { listDataRows, listDataTables } from "../api/colonyData";
import type { TaskItemRead, WorkerRead } from "../api/colonies";
import { statusText } from "../utils/format";
import { WorkerMap } from "./WorkerMap";

interface ColonySidebarProps {
  colonyId?: string;
  tasks: TaskItemRead[];
  workers: WorkerRead[];
  onSelectWorker: (worker: WorkerRead) => void;
  defaultTab?: InspectorTab;
  planContent?: ReactNode;
}

type InspectorTab = "data" | "plan" | "workers";
const PAGE_SIZE = 100;

export function ColonySidebar({
  colonyId,
  tasks,
  workers,
  onSelectWorker,
  defaultTab = "data",
  planContent,
}: ColonySidebarProps) {
  const [tab, setTab] = useState<InspectorTab>(defaultTab);
  const [selectedTable, setSelectedTable] = useState("");
  const [offset, setOffset] = useState(0);
  const [orderBy, setOrderBy] = useState<string>();
  const [orderDir, setOrderDir] = useState<"asc" | "desc">("asc");
  const hasPlanContent = Boolean(planContent);
  const tablesQuery = useQuery({
    queryKey: ["colony-data", colonyId, "tables"],
    queryFn: () => listDataTables(requireColonyId(colonyId)),
    enabled: Boolean(colonyId),
  });
  const tables = tablesQuery.data ?? [];
  const activeTable = tables.some((table) => table.name === selectedTable)
    ? selectedTable
    : tables[0]?.name ?? "";
  const rowsQuery = useQuery({
    queryKey: ["colony-data", colonyId, "rows", activeTable, offset, orderBy, orderDir],
    queryFn: () => listDataRows(requireColonyId(colonyId), activeTable, {
      limit: PAGE_SIZE,
      offset,
      orderBy,
      orderDir,
    }),
    enabled: Boolean(colonyId && activeTable),
  });
  const rowPage = rowsQuery.data;
  const dataCount = tables.length;

  function chooseTable(name: string) {
    setSelectedTable(name);
    setOffset(0);
    setOrderBy(undefined);
    setOrderDir("asc");
  }

  function sortBy(column: string) {
    setOffset(0);
    if (orderBy === column) setOrderDir((current) => current === "asc" ? "desc" : "asc");
    else {
      setOrderBy(column);
      setOrderDir("asc");
    }
  }

  return (
    <aside className="workspace-inspector" aria-label="协作详情">
      <div className="inspector-tabs" role="tablist" aria-label="协作详情分类">
        <InspectorTabButton active={tab === "data"} count={dataCount} label="Data" onClick={() => setTab("data")} />
        <InspectorTabButton active={tab === "plan"} count={tasks.length + (hasPlanContent ? 1 : 0)} label="Plan" onClick={() => setTab("plan")} />
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
                  <div><strong>{task.title}</strong><small>{statusText(task.status)}</small></div>
                </li>
              ))}
            </ol>
          </section>
        ) : null}

        {tab === "data" ? (
          <section className="data-workspace" aria-labelledby="data-title">
            <h2 className="sr-only" id="data-title">结构化数据</h2>
            {!colonyId || (!tablesQuery.isLoading && tables.length === 0) ? (
              <div className="inspector-empty">
                <span>▦</span><strong>暂无数据</strong>
                <p>Queen 创建业务表后，Worker 的结构化结果会逐行显示在这里。</p>
              </div>
            ) : null}
            {tablesQuery.isError ? <p className="form-error">Data 表加载失败</p> : null}
            {tables.length > 0 ? (
              <div className="data-toolbar" aria-label="Tracker 数据表">
                {tables.map((table) => (
                  <button
                    className={table.name === activeTable ? "active" : ""}
                    key={table.name}
                    onClick={() => chooseTable(table.name)}
                    type="button"
                  >
                    {displayLabel(table.name)} <span>{table.row_count}</span>
                  </button>
                ))}
              </div>
            ) : null}
            {rowPage ? (
              <div className="tracker-table-wrap">
                <table className="tracker-table">
                  <thead>
                    <tr>{rowPage.columns.map((column) => (
                      <th key={column.name}>
                        <button className="data-sort" onClick={() => sortBy(column.name)} type="button">
                          {column.primary_key_position > 0 ? <span className="primary-key">PK</span> : null}
                          {displayLabel(column.name)}
                          {orderBy === column.name ? (orderDir === "asc" ? " ↑" : " ↓") : null}
                        </button>
                      </th>
                    ))}</tr>
                  </thead>
                  <tbody>{rowPage.rows.map((row, index) => (
                    <tr key={rowKey(row, rowPage.primary_key, index)}>
                      {rowPage.columns.map((column) => (
                        <td key={column.name} title={readableValue(row[column.name])}>
                          {readableValue(row[column.name])}
                        </td>
                      ))}
                    </tr>
                  ))}</tbody>
                </table>
                <footer>
                  <span>{rowPage.total} rows · Tracker SQLite</span>
                  <span className="data-pagination">
                    <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} type="button">Prev</button>
                    <button disabled={offset + PAGE_SIZE >= rowPage.total} onClick={() => setOffset(offset + PAGE_SIZE)} type="button">Next</button>
                  </span>
                </footer>
              </div>
            ) : null}
          </section>
        ) : null}

        {tab === "workers" ? <WorkerMap embedded onSelect={onSelectWorker} workers={workers} /> : null}
      </div>
    </aside>
  );
}

function InspectorTabButton({ active, count, label, onClick }: {
  active: boolean;
  count?: number;
  label: string;
  onClick: () => void;
}) {
  return (
    <button aria-label={`${tabAccessibleLabel(label)}${count !== undefined ? ` ${count}` : ""}`} aria-selected={active} className={active ? "active" : ""} onClick={onClick} role="tab" type="button">
      {label}{count !== undefined ? <span>{count}</span> : null}
    </button>
  );
}

function tabAccessibleLabel(label: string): string {
  return ({ Data: "数据 Data", Plan: "计划 Plan", Workers: "Worker Workers" } as Record<string, string>)[label] ?? label;
}

function displayLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function readableValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") {
    try {
      const decoded: unknown = JSON.parse(value);
      if (typeof decoded === "object" && decoded !== null) return readableValue(decoded);
    } catch {
      // Plain strings are displayed unchanged.
    }
    return value;
  }
  if (Array.isArray(value)) return value.map(readableValue).join("、");
  if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${displayLabel(key)}：${readableValue(item)}`).join("；");
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

function rowKey(row: Record<string, unknown>, primaryKey: string[], index: number): string {
  const key = primaryKey.map((column) => readableValue(row[column])).join("|");
  return key || String(index);
}

function requireColonyId(value: string | undefined): string {
  if (!value) throw new Error("缺少 Colony 标识");
  return value;
}
