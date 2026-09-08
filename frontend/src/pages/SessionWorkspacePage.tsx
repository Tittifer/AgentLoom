import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import {
  dismissColonySuggestion,
  forkSessionIntoColony,
  getSession,
  listMessages,
  submitMessage,
  type ColonySuggestion,
} from "../api/colonies";
import { ChatPanel } from "../components/ChatPanel";
import { SessionNavigation } from "../components/SessionNavigation";
import { useSessionEvents } from "../hooks/useColonyEvents";
import { formatError } from "../utils/format";

export function SessionWorkspacePage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const sessionQuery = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => getSession(requireId(sessionId)),
    enabled: Boolean(sessionId),
    refetchInterval: 10_000,
  });
  const messagesQuery = useQuery({
    queryKey: ["messages", sessionId],
    queryFn: () => listMessages(requireId(sessionId)),
    enabled: Boolean(sessionId),
  });
  const messageMutation = useMutation({
    mutationFn: (content: string) => submitMessage(requireId(sessionId), content),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["messages", sessionId] }),
        queryClient.invalidateQueries({ queryKey: ["session", sessionId] }),
      ]);
    },
  });
  const suggestion = sessionQuery.data?.pending_colony_suggestion;
  const forkMutation = useMutation({
    mutationFn: (draft: { name: string; description: string }) => forkSessionIntoColony(requireId(sessionId), {
      suggestion_id: requireId(suggestion?.id),
      name: draft.name,
      description: draft.description,
    }),
    onSuccess: async (colony) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["colonies"] }),
        queryClient.invalidateQueries({ queryKey: ["queen-sessions"] }),
      ]);
      navigate(`/colonies/${colony.id}`);
    },
  });
  const dismissMutation = useMutation({
    mutationFn: () => dismissColonySuggestion(requireId(sessionId)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
    },
  });
  const streamingMessage = useSessionEvents(
    sessionId,
    (messagesQuery.data ?? []).map((message) => message.id),
  );

  if (sessionQuery.isLoading) return <div className="panel loading-panel">正在进入会话…</div>;
  if (sessionQuery.isError || !sessionQuery.data) {
    return (
      <div className="panel error-panel">
        <h2>无法打开会话</h2><p>{formatError(sessionQuery.error)}</p>
      </div>
    );
  }
  const session = sessionQuery.data;
  if (session.session_kind !== "dm") {
    return session.colony_id ? <Navigate replace to={`/colonies/${session.colony_id}`} /> : null;
  }

  return (
    <section className="workspace-page" aria-labelledby="workspace-title">
      <div className="workspace-shell dm-workspace-shell">
        <SessionNavigation currentSessionId={session.id} queenId={session.queen_id} />
        <div className="conversation-workspace">
          <header className="workspace-heading">
            <div className="workspace-identity"><span className="workspace-mark" aria-hidden="true">◇</span><h1 id="workspace-title">独立 Queen 会话</h1><span className="role-chip">Private DM</span></div>
            <div className="workspace-actions">
              <span className="status-pill">{session.status === "forked" ? "已创建 Colony" : "独立模式"}</span>
            </div>
          </header>
          {session.status === "forked" && session.forked_to_colony_id ? (
            <div className="forked-session-notice">
              该会话已锁定并转入 Colony。
              <Link to={`/colonies/${session.forked_to_colony_id}`}>进入协作空间</Link>
            </div>
          ) : null}
          {messageMutation.isError ? <div className="form-error">{formatError(messageMutation.error)}</div> : null}
          <ChatPanel
            activeWorkerCount={0}
            messages={messagesQuery.data ?? []}
            onSend={async (content) => { await messageMutation.mutateAsync(content); }}
            sending={messageMutation.isPending || session.status === "forked"}
            session={session}
            streamingMessage={streamingMessage}
          />
        </div>
        <aside className="workspace-inspector suggestion-inspector">
          <header className="inspector-heading">
            <div><span className="section-kicker">运行方式</span><h2>Colony 建议</h2></div>
          </header>
          {suggestion?.status === "pending" ? (
            <ColonySuggestionCard
              busy={forkMutation.isPending || dismissMutation.isPending}
              error={forkMutation.error ?? dismissMutation.error}
              onConfirm={(name, nextDescription) => forkMutation.mutate({
                name,
                description: nextDescription,
              })}
              onDismiss={() => dismissMutation.mutate()}
              suggestion={suggestion}
            />
          ) : (
            <div className="empty-copy">Queen 判断需要多智能体协作时，会在这里提交创建建议；未经确认不会启动 Worker。</div>
          )}
        </aside>
      </div>
    </section>
  );
}

interface ColonySuggestionCardProps {
  suggestion: ColonySuggestion;
  busy: boolean;
  error: Error | null;
  onConfirm: (name: string, description: string) => void;
  onDismiss: () => void;
}

function ColonySuggestionCard({
  suggestion,
  busy,
  error,
  onConfirm,
  onDismiss,
}: ColonySuggestionCardProps) {
  const [name, setName] = useState(suggestion.suggested_name);
  const [description, setDescription] = useState(suggestion.goal);

  function submit(event: FormEvent) {
    event.preventDefault();
    const normalizedName = name.trim();
    if (normalizedName) onConfirm(normalizedName, description.trim());
  }

  return (
    <form className="colony-suggestion-card" onSubmit={submit}>
      <span className="suggestion-badge">Queen 建议并行协作</span>
      <p>{suggestion.reason}</p>
      <label>
        <span>Colony 名称</span>
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label>
        <span>目标说明</span>
        <textarea rows={4} value={description} onChange={(event) => setDescription(event.target.value)} />
      </label>
      {suggestion.proposed_tasks.length > 0 ? (
        <div>
          <strong>初始任务</strong>
          <ul>{suggestion.proposed_tasks.map((task) => <li key={task}>{task}</li>)}</ul>
        </div>
      ) : null}
      {error ? <div className="form-error">{formatError(error)}</div> : null}
      <div className="suggestion-actions">
        <button disabled={busy} onClick={onDismiss} type="button">暂不创建</button>
        <button className="primary-button" disabled={!name.trim() || busy} type="submit">
          {busy ? "创建中…" : "确认创建 Colony"}
        </button>
      </div>
    </form>
  );
}

function requireId(value: string | undefined): string {
  if (!value) throw new Error("缺少资源标识");
  return value;
}
