import { apiClient } from "./client";

export interface QueenRead {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  default_model: string;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface QueenCreate {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  default_model: string;
  settings: Record<string, unknown>;
}

export function listQueens(): Promise<QueenRead[]> {
  return apiClient.get("/api/queens");
}

export function createQueen(payload: QueenCreate): Promise<QueenRead> {
  return apiClient.post("/api/queens", payload);
}
