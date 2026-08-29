import { apiClient } from "./client";

export type ColonyStatus = "draft" | "active" | "paused" | "completed" | "failed" | "archived";
export type SessionStatus =
  | "idle"
  | "queued"
  | "running"
  | "parked"
  | "completed"
  | "failed"
  | "cancelled";
export type WorkerStatus =
  | "queued"
  | "running"
  | "reporting"
  | "completed"
  | "partial"
  | "failed"
  | "timed_out"
  | "cancelled";

export interface ColonyCreate {
  name: string;
  description: string;
  queen_profile: string;
  model?: string;
  settings: Record<string, unknown>;
}

export interface ColonyRead extends ColonyCreate {
  id: string;
  status: ColonyStatus;
  model: string;
  queen_session_id: string;
  created_at: string;
  updated_at: string;
}

export interface SessionRead {
  id: string;
  colony_id: string;
  parent_session_id: string | null;
  actor_type: "queen" | "worker";
  status: SessionStatus;
  park_reason: string | null;
  task: Record<string, unknown>;
  cursor: Record<string, unknown>;
  budget: Record<string, unknown>;
  usage: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  ended_at: string | null;
}

export interface MessageRead {
  id: string;
  session_id: string;
  sequence: number;
  role: string;
  content: string;
  tool_call_id: string | null;
  tool_calls: Array<Record<string, unknown>>;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface WorkerRead {
  id: string;
  colony_id: string;
  queen_session_id: string;
  worker_session_id: string;
  status: WorkerStatus;
  task: string;
  input: Record<string, unknown>;
  report: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  timeout_seconds: number;
  queued_at: string;
  started_at: string | null;
  ended_at: string | null;
}

export interface TaskItemRead {
  id: string;
  colony_id: string;
  session_id: string;
  parent_id: string | null;
  title: string;
  description: string;
  status: string;
  position: number;
  assigned_worker_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TrackerEntryRead {
  id: string;
  colony_id: string;
  namespace: string;
  entry_key: string;
  status: string;
  data: Record<string, unknown>;
  version: number;
  updated_by_session_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ColonySnapshot {
  colony: ColonyRead;
  queen_session: SessionRead;
  workers: WorkerRead[];
  tasks: TaskItemRead[];
  tracker: TrackerEntryRead[];
}

export function listColonies(): Promise<ColonyRead[]> {
  return apiClient.get("/api/colonies");
}

export function createColony(payload: ColonyCreate): Promise<ColonyRead> {
  return apiClient.post("/api/colonies", payload);
}

export function getColony(colonyId: string): Promise<ColonySnapshot> {
  return apiClient.get(`/api/colonies/${colonyId}`);
}

export function listMessages(sessionId: string): Promise<MessageRead[]> {
  return apiClient.get(`/api/sessions/${sessionId}/messages`);
}

export function submitMessage(sessionId: string, content: string): Promise<MessageRead> {
  return apiClient.post(`/api/sessions/${sessionId}/messages`, { content });
}
