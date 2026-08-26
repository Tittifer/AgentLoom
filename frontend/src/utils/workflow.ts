const STATUS_COLORS: Record<string, string> = {
  pending: "#94a3b8",
  running: "#2563eb",
  reviewing: "#7c3aed",
  retrying: "#d97706",
  completed: "#16a34a",
  failed: "#dc2626",
  skipped: "#64748b",
  cancelled: "#475569",
};

export function getNodeStatusColor(status: string): string {
  return STATUS_COLORS[status] ?? STATUS_COLORS.pending;
}
