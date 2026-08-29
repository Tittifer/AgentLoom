import { FormEvent, useState } from "react";

import type { MessageRead, SessionRead } from "../api/colonies";
import { formatDateTime, statusText } from "../utils/format";

interface ChatPanelProps {
  session: SessionRead;
  messages: MessageRead[];
  sending: boolean;
  onSend: (content: string) => Promise<void>;
}

export function ChatPanel({ session, messages, sending, onSend }: ChatPanelProps) {
  const [content, setContent] = useState("");

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
          <span className="section-kicker">QUEEN 对话</span>
          <h2 id="chat-title">持续协作会话</h2>
        </div>
        <span className={`status-pill status-${session.status}`}>{statusText(session.status)}</span>
      </header>

      <div className="chat-messages" aria-live="polite">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <strong>Queen 已就绪</strong>
            <p>直接描述目标。Queen 会持续对话，并在适合时动态派生并行 Worker。</p>
          </div>
        ) : null}
        {messages.map((message) => (
          <article className={`chat-message role-${message.role}`} key={message.id}>
            <header>
              <strong>{roleText(message.role)}</strong>
              <time>{formatDateTime(message.created_at)}</time>
            </header>
            <div>{renderContent(message)}</div>
          </article>
        ))}
      </div>

      <form className="chat-composer" onSubmit={(event) => void submit(event)}>
        <textarea
          aria-label="发送给 Queen 的消息"
          onChange={(event) => setContent(event.target.value)}
          placeholder="告诉 Queen 你的目标、补充信息或调整要求……"
          rows={3}
          value={content}
        />
        <button className="primary-button" disabled={!content.trim() || sending} type="submit">
          {sending ? "发送中…" : "发送给 Queen"}
        </button>
      </form>
    </section>
  );
}

function roleText(role: string) {
  const labels: Record<string, string> = {
    user: "你",
    assistant: "Queen",
    tool: "工具结果",
    reviewer: "质量检查",
    system: "系统",
  };
  return labels[role] ?? role;
}

function renderContent(message: MessageRead) {
  if (message.role === "tool" || message.role === "reviewer") {
    return <pre>{message.content}</pre>;
  }
  return <p>{message.content || (message.tool_calls.length ? "正在调用工具…" : "")}</p>;
}
