import { FormEvent, useEffect, useRef, useState } from "react";

import type { MessageRead, SessionRead, WorkerRead } from "../api/colonies";
import type { StreamingAssistantMessage } from "../hooks/useColonyEvents";
import { formatDateTime } from "../utils/format";
import { MarkdownContent } from "./MarkdownContent";
import { WorkerCard } from "./WorkerCard";

interface ChatPanelProps {
  session: SessionRead;
  messages: MessageRead[];
  activeWorkerCount: number;
  sending: boolean;
  streamingMessage: StreamingAssistantMessage | null;
  workers?: WorkerRead[];
  onSelectWorker?: (worker: WorkerRead) => void;
  onSend: (content: string) => Promise<void>;
}

export function ChatPanel({
  session,
  messages,
  activeWorkerCount,
  sending,
  streamingMessage,
  workers = [],
  onSelectWorker,
  onSend,
}: ChatPanelProps) {
  const [content, setContent] = useState("");
  const messagesElement = useRef<HTMLDivElement>(null);
  const visibleMessages = messages
    .filter(isVisibleTimelineMessage)
    .filter((message) => message.id !== streamingMessage?.id);
  const workerIds = new Set(workers.map((worker) => worker.id));
  const workerReports = new Map(
    visibleMessages
      .filter(isWorkerReport)
      .map((message) => [String(message.metadata.worker_run_id), workerReportContent(message.content)]),
  );
  const timeline = [
    ...visibleMessages
      .filter((message) => !isWorkerReport(message) || !workerIds.has(String(message.metadata.worker_run_id)))
      .map((message, index) => ({ kind: "message" as const, time: message.created_at, index, message })),
    ...workers.map((worker, index) => ({ kind: "worker" as const, time: worker.queued_at, index, worker })),
  ].sort((left, right) => left.time.localeCompare(right.time) || left.index - right.index);
  const isWaiting = !streamingMessage && (
    sending ||
    session.status === "queued" ||
    session.status === "running" ||
    activeWorkerCount > 0
  );

  useEffect(() => {
    const element = messagesElement.current;
    if (!element) return;
    const scrollToLatest = () => {
      element.scrollTop = element.scrollHeight;
    };
    scrollToLatest();
    const observer = new MutationObserver(scrollToLatest);
    observer.observe(element, { childList: true, subtree: true, characterData: true });
    return () => observer.disconnect();
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const value = content.trim();
    if (!value || sending) return;
    setContent("");
    await onSend(value);
  }

  return (
    <section className="workspace-panel chat-panel" aria-labelledby="chat-title">
      <header className="panel-title-row">
        <div>
          <h2 id="chat-title">CONVERSATION</h2>
        </div>
        <span className={`status-pill status-${session.status}`}>{sessionStatusText(session.status)}</span>
      </header>

      <div className="chat-messages" aria-live="polite" ref={messagesElement}>
        {timeline.length === 0 && !streamingMessage ? (
          <div className="chat-empty">
            <span className="chat-empty-mark" aria-hidden="true">Q</span>
            <strong>已经准备好了</strong>
            <p>继续描述目标、补充信息或调整要求，协作过程会自动推进。</p>
          </div>
        ) : null}
        {timeline.map((entry) => {
          if (entry.kind === "worker") {
            return (
              <WorkerCard
                key={`worker-${entry.worker.id}`}
                onSelect={onSelectWorker}
                reportContent={workerReports.get(entry.worker.id)}
                worker={entry.worker}
              />
            );
          }
          const message = entry.message;
          if (isToolActivity(message)) {
            return (
              <article className="timeline-activity" key={message.id}>
                <span className="activity-icon" aria-hidden="true">⌘</span>
                <div>
                  {message.content.trim() ? <p>{message.content}</p> : <p>Queen 正在调用协作工具</p>}
                  <div className="tool-chip-list">{toolNames(message).map((name, index) => <span key={`${name}-${index}`}>✓ {name}</span>)}</div>
                </div>
              </article>
            );
          }
          if (isWorkerReport(message)) {
            const workerId = String(message.metadata.worker_run_id ?? "");
            return (
              <article className="worker-activity-card" key={message.id}>
                <span className="activity-icon worker-icon" aria-hidden="true">◇</span>
                <div className="worker-activity-content">
                  <header><strong>Worker</strong><code>{workerId.slice(0, 8)}</code><time>{formatDateTime(message.created_at)}</time></header>
                  <MarkdownContent content={workerReportContent(message.content)} />
                </div>
              </article>
            );
          }
          return (
            <article className={`chat-message role-${message.role}`} key={message.id}>
              {message.role === "assistant" ? (
                <span className="message-avatar" aria-hidden="true">Q</span>
              ) : null}
              <div className="message-surface">
                <header>
                  <strong>{roleText(message.role)}</strong>
                  <time>{formatDateTime(message.created_at)}</time>
                </header>
                {message.role === "assistant" ? (
                  <MarkdownContent content={message.content} />
                ) : (
                  <p>{message.content}</p>
                )}
              </div>
            </article>
          );
        })}
        {streamingMessage ? (
          <article className="chat-message role-assistant" key={streamingMessage.id}>
            <span className="message-avatar" aria-hidden="true">Q</span>
            <div className="message-surface">
              <header><strong>Queen</strong><span>正在生成</span></header>
              <MarkdownContent
                content={streamingMessage.content}
                trailing={<span className="streaming-cursor" aria-hidden="true" />}
              />
            </div>
          </article>
        ) : null}
        {isWaiting ? (
          <div className="agent-waiting" role="status">
            <span className="waiting-orbit" aria-hidden="true"><i /><i /><i /></span>
            <span className="agent-waiting-copy">
              <strong>
                {activeWorkerCount > 0
                  ? `${activeWorkerCount} 个协作节点正在执行任务`
                  : "正在分析并组织回复"}
              </strong>
              <small>AgentLoom 会在结果准备好后继续回复</small>
            </span>
            <span className="waiting-dots" aria-hidden="true"><i /><i /><i /></span>
          </div>
        ) : null}
      </div>

      <form className="chat-composer" onSubmit={(event) => void submit(event)}>
        <div className="composer-field">
          <textarea
            aria-label="输入消息"
            onChange={(event) => setContent(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Message Queen…"
            rows={2}
            value={content}
          />
          <small>Enter 发送 · Shift + Enter 换行</small>
        </div>
        <button aria-label={sending ? "发送中" : "发送"} className="primary-button composer-send" disabled={!content.trim() || sending} type="submit">
          <span aria-hidden="true">↗</span>
        </button>
      </form>
    </section>
  );
}

function roleText(role: string) {
  const labels: Record<string, string> = {
    user: "你",
    assistant: "Queen",
  };
  return labels[role] ?? role;
}

function isVisibleTimelineMessage(message: MessageRead): boolean {
  if (message.role === "tool") return false;
  if (isWorkerReport(message) || isToolActivity(message)) return true;
  return ["user", "assistant"].includes(message.role) && Boolean(message.content.trim());
}

function isWorkerReport(message: MessageRead): boolean {
  return message.role === "user" && "worker_run_id" in message.metadata;
}

function isToolActivity(message: MessageRead): boolean {
  return message.role === "assistant" && message.tool_calls.length > 0;
}

function toolNames(message: MessageRead): string[] {
  return message.tool_calls.map((call) => {
    if (typeof call.name === "string") return call.name;
    const fn = call.function;
    if (typeof fn === "object" && fn !== null && "name" in fn) return String(fn.name);
    return "tool";
  });
}

function workerReportContent(content: string): string {
  const report = content.replace(/^\s*\[WORKER_REPORT\]\s*/i, "").trim();
  if (!report) return "Worker 已完成本轮执行。";
  try {
    const payload: unknown = JSON.parse(report);
    if (typeof payload === "object" && payload !== null && "summary" in payload) {
      const summary = payload.summary;
      if (typeof summary === "string" && summary.trim()) return summary;
    }
  } catch {
    return report;
  }
  return report;
}

function sessionStatusText(status: SessionRead["status"]): string {
  if (status === "queued" || status === "running") return "思考中";
  if (status === "failed") return "需要重试";
  if (status === "forked") return "已创建 Colony";
  return "已就绪";
}
