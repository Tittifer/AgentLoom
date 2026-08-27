import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listTasks } from "../api/tasks";
import { formatDate, formatError, humanize } from "../utils/format";

const PAGE_SIZE = 10;

export function TaskListPage() {
  const [page, setPage] = useState(1);
  const tasksQuery = useQuery({
    queryKey: ["tasks", page],
    queryFn: () => listTasks(page, PAGE_SIZE),
    refetchInterval: 5_000,
  });
  const totalPages = Math.max(1, Math.ceil((tasksQuery.data?.total ?? 0) / PAGE_SIZE));

  return (
    <section aria-labelledby="tasks-title">
      <div className="page-heading">
        <div>
          <span className="eyebrow">工作台</span>
          <h1 id="tasks-title">任务</h1>
          <p>在一个页面中创建、规划并监控多智能体工作流。</p>
        </div>
        <Link className="primary-button button-link" to="/tasks/new">
          新建任务
        </Link>
      </div>

      {tasksQuery.isLoading ? <div className="panel loading-panel">正在加载任务…</div> : null}
      {tasksQuery.isError ? (
        <div className="panel error-panel">
          <h2>无法加载任务</h2>
          <p>{formatError(tasksQuery.error)}</p>
          <button className="secondary-button" onClick={() => void tasksQuery.refetch()} type="button">
            重试
          </button>
        </div>
      ) : null}

      {tasksQuery.data?.items.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon" aria-hidden="true">◇</div>
          <h2>还没有任务</h2>
          <p>创建一个任务，生成你的第一个多智能体工作流。</p>
          <Link className="primary-button button-link" to="/tasks/new">创建任务</Link>
        </div>
      ) : null}

      {tasksQuery.data && tasksQuery.data.items.length > 0 ? (
        <>
          <div className="task-table-wrap panel">
            <table className="task-table">
              <thead>
                <tr>
                  <th>任务</th>
                  <th>状态</th>
                  <th>并行节点</th>
                  <th>创建时间</th>
                  <th><span className="sr-only">操作</span></th>
                </tr>
              </thead>
              <tbody>
                {tasksQuery.data.items.map((task) => (
                  <tr key={task.id}>
                    <td>
                      <strong>{task.title}</strong>
                      <span>{task.goal}</span>
                    </td>
                    <td><span className={`status-badge status-${task.status}`}>{humanize(task.status)}</span></td>
                    <td>{task.max_parallel_nodes} 个</td>
                    <td>{formatDate(task.created_at)}</td>
                    <td><Link className="text-link" to={`/tasks/${task.id}`}>查看</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination" aria-label="任务分页">
            <button disabled={page === 1} onClick={() => setPage((value) => value - 1)} type="button">上一页</button>
            <span>第 {page} 页，共 {totalPages} 页</span>
            <button disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)} type="button">下一页</button>
          </div>
        </>
      ) : null}
    </section>
  );
}
