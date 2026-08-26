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
          <span className="eyebrow">Workspace</span>
          <h1 id="tasks-title">Tasks</h1>
          <p>Create, plan, and monitor multi-agent workflows from one place.</p>
        </div>
        <Link className="primary-button button-link" to="/tasks/new">
          New task
        </Link>
      </div>

      {tasksQuery.isLoading ? <div className="panel loading-panel">Loading tasks…</div> : null}
      {tasksQuery.isError ? (
        <div className="panel error-panel">
          <h2>Tasks could not be loaded</h2>
          <p>{formatError(tasksQuery.error)}</p>
          <button className="secondary-button" onClick={() => void tasksQuery.refetch()} type="button">
            Retry
          </button>
        </div>
      ) : null}

      {tasksQuery.data?.items.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon" aria-hidden="true">◇</div>
          <h2>No tasks yet</h2>
          <p>Create a task to generate your first multi-agent workflow.</p>
          <Link className="primary-button button-link" to="/tasks/new">Create task</Link>
        </div>
      ) : null}

      {tasksQuery.data && tasksQuery.data.items.length > 0 ? (
        <>
          <div className="task-table-wrap panel">
            <table className="task-table">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Status</th>
                  <th>Parallelism</th>
                  <th>Created</th>
                  <th><span className="sr-only">Actions</span></th>
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
                    <td>{task.max_parallel_nodes} nodes</td>
                    <td>{formatDate(task.created_at)}</td>
                    <td><Link className="text-link" to={`/tasks/${task.id}`}>View</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination" aria-label="Task pagination">
            <button disabled={page === 1} onClick={() => setPage((value) => value - 1)} type="button">Previous</button>
            <span>Page {page} of {totalPages}</span>
            <button disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)} type="button">Next</button>
          </div>
        </>
      ) : null}
    </section>
  );
}
