import { apiClient } from "./client";

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export type JsonObject = Record<string, JsonValue>;

export type TaskStatus =
  | "draft"
  | "planning"
  | "ready"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface TaskCreateInput {
  title: string;
  goal: string;
  context: JsonObject;
  max_parallel_nodes: number;
  max_retries: number;
}

export interface TaskRead extends TaskCreateInput {
  id: string;
  status: TaskStatus;
  created_at: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface WorkflowNodeRead {
  id: string;
  key: string;
  name: string;
  role: string;
  description: string;
  system_prompt: string;
  depends_on: string[];
  tools: string[];
  output_schema: JsonObject;
  review_criteria: string | null;
  sort_order: number;
}

export interface WorkflowEdgeRead {
  id: string;
  source_node_key: string;
  target_node_key: string;
}

export interface WorkflowRead {
  id: string;
  task_id: string;
  version: number;
  status: string;
  final_node: string;
  created_at: string;
  nodes: WorkflowNodeRead[];
  edges: WorkflowEdgeRead[];
}

export function listTasks(page = 1, pageSize = 20): Promise<PaginatedResponse<TaskRead>> {
  return apiClient.get<PaginatedResponse<TaskRead>>(
    `/api/tasks?page=${page}&page_size=${pageSize}`,
  );
}

export function createTask(input: TaskCreateInput): Promise<TaskRead> {
  return apiClient.post<TaskRead, TaskCreateInput>("/api/tasks", input);
}

export function getTask(taskId: string): Promise<TaskRead> {
  return apiClient.get<TaskRead>(`/api/tasks/${taskId}`);
}

export function planTask(taskId: string): Promise<WorkflowRead> {
  return apiClient.post<WorkflowRead>(`/api/tasks/${taskId}/plan`);
}

export function getTaskWorkflow(taskId: string): Promise<WorkflowRead> {
  return apiClient.get<WorkflowRead>(`/api/tasks/${taskId}/workflow`);
}
