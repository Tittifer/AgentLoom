import { apiClient } from "./client";
import type { JsonObject, WorkflowRead } from "./tasks";

export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type NodeRunStatus =
  | "pending"
  | "running"
  | "reviewing"
  | "retrying"
  | "completed"
  | "failed"
  | "skipped"
  | "cancelled";

export interface RunRead {
  id: string;
  task_id: string;
  workflow_id: string;
  status: RunStatus;
  input: JsonObject;
  result: JsonObject | null;
  error: JsonObject | null;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
}

export interface NodeRunRead {
  id: string;
  run_id: string;
  node_key: string;
  status: NodeRunStatus;
  attempt: number;
  input: JsonObject;
  output: JsonObject | null;
  review: JsonObject | null;
  usage: JsonObject | null;
  error: JsonObject | null;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
}

export interface AgentMessageRead {
  id: string;
  node_run_id: string;
  role: string;
  content: string;
  tool_calls: JsonObject[];
  created_at: string;
}

export interface RunSnapshot {
  run: RunRead;
  workflow: WorkflowRead;
  node_runs: NodeRunRead[];
  upstream_outputs: Record<string, Record<string, JsonObject>>;
  current_running_nodes: number;
  max_parallel_nodes: number;
}

export function startRun(taskId: string): Promise<RunRead> {
  return apiClient.post<RunRead>(`/api/tasks/${taskId}/runs`);
}

export function getRun(runId: string): Promise<RunSnapshot> {
  return apiClient.get<RunSnapshot>(`/api/runs/${runId}`);
}

export function getNodeAttempts(runId: string, nodeKey: string): Promise<NodeRunRead[]> {
  return apiClient.get<NodeRunRead[]>(
    `/api/runs/${runId}/nodes/${encodeURIComponent(nodeKey)}/attempts`,
  );
}

export function getNodeMessages(nodeRunId: string): Promise<AgentMessageRead[]> {
  return apiClient.get<AgentMessageRead[]>(`/api/node-runs/${nodeRunId}/messages`);
}
