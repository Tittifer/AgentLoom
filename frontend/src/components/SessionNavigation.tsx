import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import {
  deleteColony,
  deleteSession,
  listColonies,
  type SessionRead,
} from "../api/colonies";
import {
  createQueenSession,
  listQueens,
  listQueenSessions,
  type QueenRead,
} from "../api/queens";
import { formatError, statusText } from "../utils/format";
import { QueenCreateDialog } from "./QueenCreateDialog";

interface SessionNavigationProps {
  queenId?: string;
  currentSessionId?: string;
}

export function SessionNavigation({ queenId = "", currentSessionId }: SessionNavigationProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [showCreateQueen, setShowCreateQueen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const queensQuery = useQuery({ queryKey: ["queens"], queryFn: listQueens });
  const sessionsQuery = useQuery({
    queryKey: ["queen-sessions", queenId],
    queryFn: () => listQueenSessions(queenId),
    enabled: Boolean(queenId),
  });
  const coloniesQuery = useQuery({ queryKey: ["colonies"], queryFn: listColonies });

  const createSessionMutation = useMutation({
    mutationFn: createQueenSession,
    onSuccess: async (session) => {
      queryClient.setQueryData(["session", session.id], session);
      queryClient.setQueryData(["messages", session.id], []);
      await queryClient.invalidateQueries({ queryKey: ["queen-sessions", session.queen_id] });
      navigate(`/sessions/${session.id}`);
    },
  });
  const openQueenMutation = useMutation({
    mutationFn: async (selectedQueenId: string) => {
      const sessions = await queryClient.fetchQuery({
        queryKey: ["queen-sessions", selectedQueenId],
        queryFn: () => listQueenSessions(selectedQueenId),
      });
      const latest = [...sessions].sort(
        (left, right) => right.updated_at.localeCompare(left.updated_at),
      )[0];
      if (latest) return sessionDestination(latest);
      const session = await createQueenSession(selectedQueenId);
      queryClient.setQueryData(["session", session.id], session);
      queryClient.setQueryData(["messages", session.id], []);
      return `/sessions/${session.id}`;
    },
    onSuccess: (destination) => navigate(destination),
  });
  const deleteSessionMutation = useMutation({
    mutationFn: deleteSession,
    onSuccess: async (_, sessionId) => {
      await queryClient.invalidateQueries({ queryKey: ["queen-sessions", queenId] });
      if (sessionId === currentSessionId) navigate("/");
    },
  });
  const deleteColonyMutation = useMutation({
    mutationFn: deleteColony,
    onSuccess: async (_, colonyId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["colonies"] }),
        queryClient.invalidateQueries({ queryKey: ["queen-sessions", queenId] }),
      ]);
      if (location.pathname === `/colonies/${colonyId}`) navigate("/");
    },
  });

  const sessions = (sessionsQuery.data ?? [])
    .filter((session) => session.session_kind === "dm" && !session.forked_to_colony_id)
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at));
  const colonies = (coloniesQuery.data ?? [])
    .filter((colony) => colony.queen_id === queenId)
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at));
  const error = queensQuery.error
    ?? sessionsQuery.error
    ?? coloniesQuery.error
    ?? createSessionMutation.error
    ?? openQueenMutation.error
    ?? deleteSessionMutation.error
    ?? deleteColonyMutation.error;

  return (
    <aside className={`session-navigation${collapsed ? " is-collapsed" : ""}`}>
      <header className="session-navigation-header">
        <div><span className="section-kicker">工作空间</span><strong>协作会话</strong></div>
        <button
          aria-label={collapsed ? "展开会话导航" : "收起会话导航"}
          className="navigation-toggle"
          onClick={() => setCollapsed((value) => !value)}
          type="button"
        >
          {collapsed ? "›" : "‹"}
        </button>
      </header>

      <div className="navigation-primary">
        <button
          aria-label="新建会话"
          className="new-session-button"
          disabled={!queenId || createSessionMutation.isPending}
          onClick={() => createSessionMutation.mutate(queenId)}
          type="button"
        >
          <span aria-hidden="true">▣</span>
          <strong>{createSessionMutation.isPending ? "创建中…" : "新建会话"}</strong>
        </button>
      </div>

      {error ? <div className="navigation-inline-error">{formatError(error)}</div> : null}

      <NavigationSection count={sessions.length} label="CHATS">
        {sessions.map((session, index) => {
          const title = sessionTitle(session, sessions.length - index);
          return (
            <div className="sidebar-resource-row" key={session.id}>
              <NavLink
                className={({ isActive }) => `session-navigation-item${isActive ? " active" : ""}`}
                title={title}
                to={`/sessions/${session.id}`}
              >
                <span className={`session-status-dot status-dot-${session.status}`} aria-hidden="true" />
                <span className="session-navigation-copy">
                  <strong>{title}</strong><small>{statusText(session.status)}</small>
                </span>
              </NavLink>
              <button
                aria-label={`删除会话 ${title}`}
                className="sidebar-delete-button"
                disabled={deleteSessionMutation.isPending || ["queued", "running"].includes(session.status)}
                onClick={() => {
                  if (window.confirm("确定删除这条独立会话吗？会话将移动到本地回收目录。")) {
                    deleteSessionMutation.mutate(session.id);
                  }
                }}
                type="button"
              >
                ×
              </button>
            </div>
          );
        })}
      </NavigationSection>

      <NavigationSection count={colonies.length} label="COLONIES">
        {colonies.map((colony) => (
          <div className="sidebar-resource-row" key={colony.id}>
            <NavLink
              className={({ isActive }) => `session-navigation-item${isActive ? " active" : ""}`}
              title={colony.name}
              to={`/colonies/${colony.id}`}
            >
              <span className={`session-status-dot status-dot-${colony.status}`} aria-hidden="true" />
              <span className="session-navigation-copy">
                <strong>{colony.name}</strong><small>{statusText(colony.status)}</small>
              </span>
            </NavLink>
            <button
              aria-label={`删除 Colony ${colony.name}`}
              className="sidebar-delete-button"
              disabled={deleteColonyMutation.isPending}
              onClick={() => {
                if (window.confirm(`确定删除 Colony“${colony.name}”吗？`)) {
                  deleteColonyMutation.mutate(colony.id);
                }
              }}
              type="button"
            >
              ×
            </button>
          </div>
        ))}
      </NavigationSection>

      <section className="navigation-resource-section queen-bee-section" aria-labelledby="queen-bees-heading">
        <header className="navigation-section-heading queen-bee-section-heading">
          <span id="queen-bees-heading">QUEEN BEES</span><b>{queensQuery.data?.length ?? 0}</b>
          <button aria-label="新建 Queen" onClick={() => setShowCreateQueen(true)} type="button">+</button>
        </header>
        <div className="queen-bee-list">
          {queensQuery.data?.map((queen) => (
            <button
              className={`queen-bee-item${queen.id === queenId ? " active" : ""}`}
              disabled={openQueenMutation.isPending}
              key={queen.id}
              onClick={() => openQueenMutation.mutate(queen.id)}
              type="button"
            >
              <span className="queen-bee-avatar" aria-hidden="true">Q</span>
              <span><strong>{queen.name}</strong><small>{queen.description || "Queen"}</small></span>
            </button>
          ))}
        </div>
      </section>

      <small className="navigation-version">v0.1.0</small>
      <QueenCreateDialog
        onClose={() => setShowCreateQueen(false)}
        onCreated={(queen: QueenRead) => createSessionMutation.mutate(queen.id)}
        open={showCreateQueen}
      />
    </aside>
  );
}

function NavigationSection({ count, label, children }: { count: number; label: string; children: ReactNode }) {
  return (
    <section className="navigation-resource-section" aria-labelledby={`navigation-${label.toLowerCase()}`}>
      <header className="navigation-section-heading">
        <span id={`navigation-${label.toLowerCase()}`}>{label}</span><b>{count}</b>
      </header>
      <nav aria-label={label} className="session-navigation-list">{children}</nav>
    </section>
  );
}

function sessionDestination(session: SessionRead): string {
  if (session.forked_to_colony_id) return `/colonies/${session.forked_to_colony_id}`;
  if (session.colony_id) return `/colonies/${session.colony_id}`;
  return `/sessions/${session.id}`;
}

function sessionTitle(session: SessionRead, fallbackIndex: number): string {
  for (const key of ["title", "name", "description"]) {
    const value = session.task[key];
    if (typeof value === "string" && value.trim()) {
      const normalized = value.replace(/\s+/g, " ").trim();
      return normalized.length > 28 ? `${normalized.slice(0, 28)}…` : normalized;
    }
  }
  return `独立会话 ${fallbackIndex}`;
}
