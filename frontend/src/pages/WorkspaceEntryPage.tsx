import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import type { SessionRead } from "../api/colonies";
import { createQueenSession, listQueens, listQueenSessions } from "../api/queens";
import { ColonySidebar } from "../components/ColonySidebar";
import { SessionNavigation } from "../components/SessionNavigation";
import { formatError } from "../utils/format";

export function WorkspaceEntryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const creatingSession = useRef(false);
  const queensQuery = useQuery({ queryKey: ["queens"], queryFn: listQueens });
  const queenId = queensQuery.data?.[0]?.id ?? "";
  const sessionsQuery = useQuery({
    queryKey: ["queen-sessions", queenId],
    queryFn: () => listQueenSessions(queenId),
    enabled: Boolean(queenId),
  });
  const createSessionMutation = useMutation({
    mutationFn: createQueenSession,
    onSuccess: (session) => {
      queryClient.setQueryData(["session", session.id], session);
      queryClient.setQueryData(["messages", session.id], []);
      navigate(`/sessions/${session.id}`, { replace: true });
    },
    onError: () => {
      creatingSession.current = false;
    },
  });

  useEffect(() => {
    if (!queenId || !sessionsQuery.isSuccess || creatingSession.current) return;
    const latest = latestDirectSession(sessionsQuery.data);
    if (latest) {
      navigate(`/sessions/${latest.id}`, { replace: true });
      return;
    }
    creatingSession.current = true;
    createSessionMutation.mutate(queenId);
  }, [createSessionMutation, navigate, queenId, sessionsQuery.data, sessionsQuery.isSuccess]);

  const error = queensQuery.error ?? sessionsQuery.error ?? createSessionMutation.error;

  return (
    <section className="workspace-page" aria-labelledby="workspace-entry-title">
      <div className="workspace-shell entry-workspace-shell">
        <SessionNavigation queenId={queenId} />
        <div className="conversation-workspace workspace-entry">
          <div className="chat-empty">
            <div className="empty-icon" aria-hidden="true">Q</div>
            <h1 id="workspace-entry-title">{queenId ? "正在打开会话" : "开始一段新会话"}</h1>
            <p>{queenId ? "正在准备最近的独立会话。" : "在左侧新建第一个 Queen 后，会自动进入会话工作台。"}</p>
            {error ? <div className="form-error" role="alert">{formatError(error)}</div> : null}
          </div>
        </div>
        <ColonySidebar onSelectWorker={() => undefined} tasks={[]} tracker={[]} workers={[]} />
      </div>
    </section>
  );
}

function latestDirectSession(sessions: SessionRead[]): SessionRead | undefined {
  return sessions
    .filter((session) => session.session_kind === "dm" && !session.forked_to_colony_id)
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0];
}
