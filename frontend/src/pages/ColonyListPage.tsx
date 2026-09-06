import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import { deleteColony, listColonies } from "../api/colonies";
import { createQueenSession, listQueenSessions } from "../api/queens";
import { formatDateTime, formatError, statusText } from "../utils/format";

export function ColonyListPage() {
  const { queenId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const sessionsQuery = useQuery({
    queryKey: ["queen-sessions", queenId],
    queryFn: () => listQueenSessions(queenId),
    enabled: Boolean(queenId),
  });
  const coloniesQuery = useQuery({ queryKey: ["colonies"], queryFn: listColonies });
  const deleteMutation = useMutation({
    mutationFn: deleteColony,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["colonies"] }),
        queryClient.invalidateQueries({ queryKey: ["queen-sessions", queenId] }),
      ]);
    },
  });
  const createMutation = useMutation({
    mutationFn: () => createQueenSession(queenId),
    onSuccess: async (session) => {
      await queryClient.invalidateQueries({ queryKey: ["queen-sessions", queenId] });
      navigate(`/sessions/${session.id}`);
    },
  });
  const colonyById = new Map(
    (coloniesQuery.data ?? [])
      .filter((colony) => colony.queen_id === queenId)
      .map((colony) => [colony.id, colony]),
  );
  const sessions = sessionsQuery.data ?? [];

  function removeColony(colonyId: string, name: string) {
    if (window.confirm(`确定删除会话“${name}”吗？删除后无法恢复。`)) {
      deleteMutation.mutate(colonyId);
    }
  }

  return (
    <section aria-labelledby="colonies-title">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Queen 会话</span>
          <h1 id="colonies-title">我的会话</h1>
          <p>先与 Queen 独立对话；需要并行协作时，由 Queen 提议并经你确认后创建 Colony。</p>
        </div>
        <button
          className="primary-button"
          disabled={createMutation.isPending}
          onClick={() => createMutation.mutate()}
          type="button"
        >
          {createMutation.isPending ? "正在创建…" : "新建会话"}
        </button>
      </div>

      {sessionsQuery.isLoading || coloniesQuery.isLoading ? (
        <div className="panel loading-panel">正在加载会话…</div>
      ) : null}
      {sessionsQuery.isError || coloniesQuery.isError ? (
        <div className="panel error-panel">
          <h2>无法加载会话</h2>
          <p>{formatError(sessionsQuery.error ?? coloniesQuery.error)}</p>
        </div>
      ) : null}
      {deleteMutation.isError || createMutation.isError ? (
        <div className="panel error-panel">
          <p>{formatError(deleteMutation.error ?? createMutation.error)}</p>
        </div>
      ) : null}
      {!sessionsQuery.isLoading && sessions.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon" aria-hidden="true">Q</div>
          <h2>开始第一次对话</h2>
          <p>Queen 会先独立理解和处理目标，不会在创建会话时立即生成 Colony。</p>
          <button
            className="primary-button"
            disabled={createMutation.isPending}
            onClick={() => createMutation.mutate()}
            type="button"
          >
            {createMutation.isPending ? "正在创建…" : "新建会话"}
          </button>
        </div>
      ) : null}
      <div className="colony-card-grid">
        {sessions.map((session) => {
          const colony = session.colony_id ? colonyById.get(session.colony_id) : undefined;
          const destination = session.forked_to_colony_id;
          const isDm = session.session_kind === "dm";
          const href = isDm && !destination
            ? `/sessions/${session.id}`
            : `/colonies/${destination ?? session.colony_id}`;
          const name = colony?.name ?? (destination ? "已转为 Colony" : "独立 Queen 会话");
          return (
            <article className="colony-card" key={session.id}>
              <header>
                <span className="colony-avatar">Q</span>
                <div className="card-actions">
                  <span className={`status-pill status-${session.status}`}>
                    {session.status === "forked" ? "已创建 Colony" : statusText(session.status)}
                  </span>
                  {colony ? (
                    <button
                      aria-label={`删除会话 ${name}`}
                      className="delete-button"
                      disabled={deleteMutation.isPending && deleteMutation.variables === colony.id}
                      onClick={() => removeColony(colony.id, name)}
                      type="button"
                    >
                      删除
                    </button>
                  ) : null}
                </div>
              </header>
              <Link className="colony-card-link" to={href}>
                <h2>{name}</h2>
                <p>{isDm ? "独立对话" : "Colony 协作会话"}</p>
              </Link>
              <footer>
                <span>最近更新</span><time>{formatDateTime(session.updated_at)}</time>
              </footer>
            </article>
          );
        })}
      </div>
    </section>
  );
}
