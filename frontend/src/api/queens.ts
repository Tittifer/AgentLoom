import { apiClient } from "./client";

export interface QueenRead {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  created_at: string;
  updated_at: string;
}

export interface QueenCreate {
  name: string;
  description: string;
  system_prompt: string;
}

export function listQueens(): Promise<QueenRead[]> {
  return apiClient.get("/api/queens");
}

export function createQueen(payload: QueenCreate): Promise<QueenRead> {
  return apiClient.post("/api/queens", payload);
}
