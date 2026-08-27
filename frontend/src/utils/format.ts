import { ApiClientError } from "../api/client";
import type { JsonValue } from "../api/tasks";

const DISPLAY_LABELS: Record<string, string> = {
  draft: "草稿",
  planning: "规划中",
  ready: "就绪",
  queued: "排队中",
  pending: "等待中",
  running: "运行中",
  reviewing: "审核中",
  retrying: "重试中",
  completed: "已完成",
  failed: "失败",
  skipped: "已跳过",
  cancelled: "已取消",
  researcher: "研究员",
  analyst: "分析员",
  writer: "撰写员",
  system: "系统",
  user: "用户",
  assistant: "助手",
  tool: "工具",
  reviewer: "审核员",
  "run.started": "运行已开始",
  "run.recovered": "运行已恢复",
  "run.completed": "运行已完成",
  "run.failed": "运行失败",
  "run.cancelled": "运行已取消",
  "node.started": "节点已开始",
  "node.reviewed": "节点已审核",
  "node.retrying": "节点正在重试",
  "node.completed": "节点已完成",
  "node.failed": "节点失败",
  "llm.usage_recorded": "已记录模型用量",
};

const API_ERROR_MESSAGES: Record<string, string> = {
  TASK_NOT_FOUND: "任务不存在。",
  TASK_NOT_READY: "任务尚未就绪，无法启动运行。",
  TASK_NOT_PLANNABLE: "任务当前状态不允许生成工作流。",
  WORKFLOW_NOT_FOUND: "任务尚未生成工作流。",
  PLANNING_FAILED: "规划器未能生成有效的工作流。",
  PLANNER_PROVIDER_ERROR: "模型服务调用失败，请检查模型配置和服务状态。",
  RUN_NOT_FOUND: "运行记录不存在。",
  RUN_NOT_CANCELLABLE: "该运行已经结束，无法取消。",
  RUN_NOT_RETRYABLE: "只有当前失败的运行可以重试。",
  NODE_RUN_NOT_FOUND: "节点运行记录不存在。",
};

export function formatDate(value: string | null): string {
  if (!value) {
    return "—";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatJson(value: JsonValue | undefined): string {
  return JSON.stringify(value ?? null, null, 2);
}

export function formatError(error: unknown): string {
  if (error instanceof ApiClientError) {
    return (error.code && API_ERROR_MESSAGES[error.code]) || `请求失败（HTTP ${error.status}）。`;
  }
  if (error instanceof Error) {
    if (/[一-鿿]/u.test(error.message)) {
      return error.message;
    }
    if (error instanceof TypeError) {
      return "无法连接后端服务，请检查服务是否正在运行。";
    }
    return "操作失败，请稍后重试。";
  }
  return "发生未知错误，请稍后重试。";
}

export function humanize(value: string): string {
  return DISPLAY_LABELS[value] ?? value.replaceAll("_", " ").replaceAll(".", " ");
}
