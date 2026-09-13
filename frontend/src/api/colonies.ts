import { apiClient } from "./client";

export type ColonyStatus = "draft" | "active" | "paused" | "completed" | "failed" | "archived";
export type SessionStatus =
  | "idle"
  | "queued"
  | "running"
  | "parked"
  | "completed"
  | "failed"
  | "cancelled"
  | "forked";
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
  queen_id: string;
  settings: Record<string, unknown>;
}

export interface ColonyRead extends ColonyCreate {
  layout_version: 2;
  id: string;
  status: ColonyStatus;
  model: string;
  source_session_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ColonySuggestion {
  id: string;
  suggested_name: string;
  reason: string;
  goal: string;
  handoff: string;
  proposed_tasks: string[];
  status: "pending" | "accepted" | "dismissed";
  created_at: string;
}

export interface ColonyForkCreate {
  suggestion_id: string;
  name: string;
  description: string;
}

export interface SessionRead {
  layout_version: 2;
  id: string;
  colony_id: string | null;
  queen_id: string;
  mode: "dm" | "colony";
  pending_colony_suggestion: ColonySuggestion | null;
  spawned_colony_id: string | null;
  superseded_by: string | null;
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
  layout_version: 2;
  id: string;
  colony_id: string;
  owner_session_id: string;
  queen_id: string;
  status: WorkerStatus;
  park_reason: string | null;
  task: string;
  input: Record<string, unknown>;
  cursor: Record<string, unknown>;
  budget: Record<string, unknown>;
  usage: Record<string, unknown>;
  report: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  timeout_seconds: number;
  queued_at: string;
  started_at: string | null;
  updated_at: string;
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
  session: SessionRead;
  workers: WorkerRead[];
  tasks: TaskItemRead[];
  tracker: TrackerEntryRead[];
}

export interface SessionCreate {
  queen_id: string;
  colony_id?: string;
  source_session_id?: string;
}

export function listSessions(queenId?: string): Promise<SessionRead[]> {
  const query = queenId ? `?queen_id=${encodeURIComponent(queenId)}` : "";
  return apiClient.get(`/api/sessions${query}`);
}

export function createSession(payload: SessionCreate): Promise<SessionRead> {
  return apiClient.post("/api/sessions", payload);
}

export function listColonies(): Promise<ColonyRead[]> {
  return apiClient.get("/api/colonies");
}

export function createColony(payload: ColonyCreate): Promise<ColonyRead> {
  return apiClient.post("/api/colonies", payload);
}

export function deleteColony(colonyId: string): Promise<void> {
  return apiClient.delete(`/api/colonies/${colonyId}`);
}

export function getColony(colonyId: string): Promise<ColonySnapshot> {
  return apiClient.get(`/api/colonies/${colonyId}`);
}

export function listMessages(sessionId: string): Promise<MessageRead[]> {
  return apiClient.get(`/api/sessions/${sessionId}/messages`);
}

export function getSession(sessionId: string): Promise<SessionRead> {
  return apiClient.get(`/api/sessions/${sessionId}`);
}

export function deleteSession(sessionId: string): Promise<void> {
  return apiClient.delete(`/api/sessions/${sessionId}`);
}

export function forkSessionIntoColony(
  sessionId: string,
  payload: ColonyForkCreate,
): Promise<ColonyRead> {
  return apiClient.post(`/api/sessions/${sessionId}/fork-colony`, payload);
}

export function dismissColonySuggestion(sessionId: string): Promise<SessionRead> {
  return apiClient.post(`/api/sessions/${sessionId}/dismiss-colony-suggestion`, {});
}

export function submitMessage(sessionId: string, content: string): Promise<MessageRead> {
  return apiClient.post(`/api/sessions/${sessionId}/messages`, { content });
}
