import { FormEvent, useEffect, useRef, useState } from "react";

import type { MessageRead, SessionRead } from "../api/colonies";
import type { StreamingAssistantMessage } from "../hooks/useColonyEvents";
import { formatDateTime } from "../utils/format";
import { MarkdownContent } from "./MarkdownContent";

interface ChatPanelProps {
  session: SessionRead;
  messages: MessageRead[];
  activeWorkerCount: number;
  sending: boolean;
  streamingMessage: StreamingAssistantMessage | null;
  onSend: (content: string) => Promise<void>;
}

export function ChatPanel({
  session,
  messages,
  activeWorkerCount,
  sending,
  streamingMessage,
  onSend,
}: ChatPanelProps) {
  const [content, setContent] = useState("");
  const messagesElement = useRef<HTMLDivElement>(null);
  const visibleMessages = messages
    .filter(isVisibleConversationMessage)
    .filter((message) => message.id !== streamingMessage?.id);
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
          <span className="section-kicker">对话</span>
          <h2 id="chat-title">与 AgentLoom 协作</h2>
        </div>
        <span className={`status-pill status-${session.status}`}>{sessionStatusText(session.status)}</span>
      </header>

      <div className="chat-messages" aria-live="polite" ref={messagesElement}>
        {visibleMessages.length === 0 && !streamingMessage ? (
          <div className="chat-empty">
            <span className="chat-empty-mark" aria-hidden="true">AL</span>
            <strong>已经准备好了</strong>
            <p>继续描述目标、补充信息或调整要求，协作过程会自动推进。</p>
          </div>
        ) : null}
        {visibleMessages.map((message) => (
          <article className={`chat-message role-${message.role}`} key={message.id}>
            {message.role === "assistant" ? (
              <span className="message-avatar" aria-hidden="true">AL</span>
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
        ))}
        {streamingMessage ? (
          <article className="chat-message role-assistant" key={streamingMessage.id}>
            <span className="message-avatar" aria-hidden="true">AL</span>
            <div className="message-surface">
              <header><strong>AgentLoom</strong><span>正在生成</span></header>
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
            placeholder="输入补充信息或新的要求……"
            rows={2}
            value={content}
          />
          <small>Enter 发送 · Shift + Enter 换行</small>
        </div>
        <button className="primary-button" disabled={!content.trim() || sending} type="submit">
          {sending ? "发送中…" : "发送"}
        </button>
      </form>
    </section>
  );
}

function roleText(role: string) {
  const labels: Record<string, string> = {
    user: "你",
    assistant: "AgentLoom",
  };
  return labels[role] ?? role;
}

function isVisibleConversationMessage(message: MessageRead): boolean {
  if (message.role === "user") return !("worker_run_id" in message.metadata);
  return (
    message.role === "assistant" &&
    message.tool_calls.length === 0 &&
    Boolean(message.content.trim())
  );
}

function sessionStatusText(status: SessionRead["status"]): string {
  if (status === "queued" || status === "running") return "思考中";
  if (status === "failed") return "需要重试";
  return "已就绪";
}
