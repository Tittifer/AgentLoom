import { apiClient } from "./client";

export type MemoryScope = "global" | "queen";

export interface Memory {
  path: string;
  filename: string;
  scope: MemoryScope;
  queen_id: string | null;
  name: string | null;
  description: string | null;
  type: "profile" | "preference" | "environment" | "feedback" | null;
  mtime: number;
  content: string | null;
}

const filePath = (path: string) => `/api/memories/file?path=${encodeURIComponent(path)}`;

export const listMemories = () => apiClient.get<Memory[]>("/api/memories");
export const getMemory = (path: string) => apiClient.get<Memory>(filePath(path));
export const updateMemory = (path: string, content: string) =>
  apiClient.put<Memory, { content: string }>(filePath(path), { content });
export const deleteMemory = (path: string) => apiClient.delete(filePath(path));
