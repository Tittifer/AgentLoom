import { apiClient } from "./client";

export interface UserSettingsRead {
  configured: boolean;
  model: string | null;
  protocol: "openai" | "claude" | "gemini" | null;
  base_url: string | null;
  api_key_configured: boolean;
  response_format: "json_schema" | "json_object";
  max_context_tokens: number;
  updated_at: string | null;
}

export interface UserSettingsUpdate {
  model: string;
  base_url: string;
  api_key: string;
  response_format: "json_schema" | "json_object";
  max_context_tokens: number;
}

export function getUserSettings(): Promise<UserSettingsRead> {
  return apiClient.get("/api/settings");
}

export function updateUserSettings(payload: UserSettingsUpdate): Promise<UserSettingsRead> {
  return apiClient.put("/api/settings", payload);
}
