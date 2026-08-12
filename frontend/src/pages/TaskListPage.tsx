import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../api/client";

interface HealthResponse {
  status: string;
}

function getHealth(): Promise<HealthResponse> {
  return apiClient.get<HealthResponse>("/health");
}

export function TaskListPage() {
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
  });

  const backendOnline = healthQuery.data?.status === "ok";

  return (
    <section aria-labelledby="tasks-title">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Workspace</span>
          <h1 id="tasks-title">Tasks</h1>
          <p>Create, plan, and monitor multi-agent workflows from one place.</p>
        </div>
        <button className="primary-button" disabled type="button">
          New task
        </button>
      </div>

      <div className="status-card" aria-live="polite">
        <span
          className={`status-dot ${backendOnline ? "online" : healthQuery.isError ? "offline" : "checking"}`}
          aria-hidden="true"
        />
        <div>
          <strong>
            {backendOnline
              ? "Backend connected"
              : healthQuery.isError
                ? "Backend unavailable"
                : "Checking backend"}
          </strong>
          <p>
            {backendOnline
              ? "Vite proxy and FastAPI health endpoint are working."
              : healthQuery.isError
                ? "Start the backend on port 8000, then try again."
                : "Requesting /health through the shared API client…"}
          </p>
        </div>
        {healthQuery.isError ? (
          <button className="secondary-button" onClick={() => void healthQuery.refetch()} type="button">
            Retry
          </button>
        ) : null}
      </div>

      <div className="empty-state">
        <div className="empty-icon" aria-hidden="true">
          ◇
        </div>
        <h2>No tasks yet</h2>
        <p>Task creation and persistence arrive in the next implementation phase.</p>
      </div>
    </section>
  );
}
