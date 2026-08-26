import { ApiClientError } from "../api/client";
import type { JsonValue } from "../api/tasks";

export function formatDate(value: string | null): string {
  if (!value) {
    return "—";
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatJson(value: JsonValue | undefined): string {
  return JSON.stringify(value ?? null, null, 2);
}

export function formatError(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

export function humanize(value: string): string {
  return value.replaceAll("_", " ").replaceAll(".", " ");
}
