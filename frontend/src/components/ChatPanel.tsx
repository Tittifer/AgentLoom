import { FormEvent, useState } from "react";

import type { MessageRead, SessionRead } from "../api/colonies";
import { formatDateTime } from "../utils/format";

interface ChatPanelProps {
  session: SessionRead;
  messages: MessageRead[];
  sending: boolean;
  onSend: (content: string) => Promise<void>;
}

export function ChatPanel({ session, messages, sending, onSend }: ChatPanelProps) {
  const [content, setContent] = useState("");
  const visibleMessages = messages.filter(isVisibleConversationMessage);

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

      <div className="chat-messages" aria-live="polite">
        {visibleMessages.length === 0 ? (
          <div className="chat-empty">
            <strong>已经准备好了</strong>
            <p>继续描述目标、补充信息或调整要求，协作过程会自动推进。</p>
          </div>
        ) : null}
        {visibleMessages.map((message) => (
          <article className={`chat-message role-${message.role}`} key={message.id}>
            <header>
              <strong>{roleText(message.role)}</strong>
              <time>{formatDateTime(message.created_at)}</time>
            </header>
            <p>{message.content}</p>
          </article>
        ))}
      </div>

      <form className="chat-composer" onSubmit={(event) => void submit(event)}>
        <textarea
          aria-label="输入消息"
          onChange={(event) => setContent(event.target.value)}
          placeholder="输入补充信息或新的要求……"
          rows={3}
          value={content}
        />
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
