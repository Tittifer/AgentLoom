import { apiClient } from "./client";

export interface TrackerColumnRead {
  name: string;
  type: string;
  notnull: boolean;
  primary_key_position: number;
  default: unknown;
}

export interface TrackerTableRead {
  name: string;
  columns: TrackerColumnRead[];
  row_count: number;
  primary_key: string[];
}

export interface TrackerRowsRead {
  table: string;
  columns: TrackerColumnRead[];
  primary_key: string[];
  rows: Array<Record<string, unknown>>;
  total: number;
  limit: number;
  offset: number;
}

export function listDataTables(colonyId: string): Promise<TrackerTableRead[]> {
  return apiClient.get(`/api/colonies/${encodeURIComponent(colonyId)}/data/tables`);
}

export function listDataRows(
  colonyId: string,
  table: string,
  options: { limit?: number; offset?: number; orderBy?: string; orderDir?: "asc" | "desc" } = {},
): Promise<TrackerRowsRead> {
  const parameters = new URLSearchParams({
    limit: String(options.limit ?? 100),
    offset: String(options.offset ?? 0),
    order_dir: options.orderDir ?? "asc",
  });
  if (options.orderBy) parameters.set("order_by", options.orderBy);
  return apiClient.get(
    `/api/colonies/${encodeURIComponent(colonyId)}/data/tables/${encodeURIComponent(table)}/rows?${parameters}`,
  );
}
