import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { listSessions, type SessionRead } from "../api/colonies";
import { listQueens } from "../api/queens";
import { ColonySidebar } from "../components/ColonySidebar";
import { SessionNavigation } from "../components/SessionNavigation";
import { formatError } from "../utils/format";

export function WorkspaceEntryPage() {
  const navigate = useNavigate();
  const queensQuery = useQuery({ queryKey: ["queens"], queryFn: listQueens });
  const queenId = queensQuery.data?.[0]?.id ?? "";
  const sessionsQuery = useQuery({
    queryKey: ["sessions", queenId],
    queryFn: () => listSessions(queenId),
    enabled: Boolean(queenId),
  });
  useEffect(() => {
    if (!queenId || !sessionsQuery.isSuccess) return;
    const latest = latestDirectSession(sessionsQuery.data);
    if (latest) navigate(`/sessions/${latest.id}`, { replace: true });
  }, [navigate, queenId, sessionsQuery.data, sessionsQuery.isSuccess]);

  const error = queensQuery.error ?? sessionsQuery.error;
  const openingExistingSession = Boolean(
    queenId && (!sessionsQuery.isSuccess || latestDirectSession(sessionsQuery.data)),
  );

  return (
    <section className="workspace-page" aria-labelledby="workspace-entry-title">
      <div className="workspace-shell entry-workspace-shell">
        <SessionNavigation queenId={queenId} />
        <div className="conversation-workspace workspace-entry">
          <div className="chat-empty">
            <div className="empty-icon" aria-hidden="true">Q</div>
            <h1 id="workspace-entry-title">
              {openingExistingSession ? "正在打开会话" : "开始一段新会话"}
            </h1>
            <p>
              {openingExistingSession
                ? "正在准备最近的独立会话。"
                : queenId
                ? "点击左侧的新建会话开始与 Queen 对话。"
                : "在左侧新建第一个 Queen 后，即可开始会话。"}
            </p>
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
    .filter((session) => session.mode === "dm" && !session.spawned_colony_id)
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0];
}
