export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function statusText(status: string): string {
  const labels: Record<string, string> = {
    draft: "草稿",
    active: "活跃",
    paused: "已暂停",
    archived: "已归档",
    idle: "等待中",
    queued: "排队中",
    running: "运行中",
    parked: "已挂起",
    reporting: "汇报中",
    completed: "已完成",
    partial: "部分完成",
    failed: "失败",
    timed_out: "已超时",
    cancelled: "已取消",
    pending: "待处理",
    in_progress: "进行中",
    blocked: "已阻塞",
  };
  return labels[status] ?? status;
}

export function formatError(error: unknown): string {
  return error instanceof Error ? error.message : "发生未知错误";
}

export function formatDate(value: string | null | undefined): string {
  return formatDateTime(value);
}

export function humanize(value: string): string {
  return statusText(value);
}

export function sessionNameFromMessage(content: string): string {
  const normalized = content.replace(/\s+/g, " ").trim();
  return normalized.length > 32 ? `${normalized.slice(0, 32)}…` : normalized;
}
