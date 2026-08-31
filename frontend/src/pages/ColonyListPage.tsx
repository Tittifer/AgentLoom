import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { createColony, deleteColony, listColonies } from "../api/colonies";
import { formatDateTime, formatError, statusText } from "../utils/format";

export function ColonyListPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["colonies"], queryFn: listColonies });
  const deleteMutation = useMutation({
    mutationFn: deleteColony,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["colonies"] });
    },
  });
  const createMutation = useMutation({
    mutationFn: () => createColony({
      name: "新会话",
      description: "",
      queen_profile: "general",
      settings: {},
    }),
    onSuccess: async (colony) => {
      await queryClient.invalidateQueries({ queryKey: ["colonies"] });
      navigate(`/colonies/${colony.id}`);
    },
  });

  function removeSession(colonyId: string, name: string) {
    if (window.confirm(`确定删除会话“${name}”吗？删除后无法恢复。`)) {
      deleteMutation.mutate(colonyId);
    }
  }

  return (
    <section aria-labelledby="colonies-title">
      <div className="page-heading">
        <div>
          <span className="eyebrow">会话列表</span>
          <h1 id="colonies-title">我的会话</h1>
          <p>从一次对话开始，让多个智能体在后台协作完成复杂目标。</p>
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

      {query.isLoading ? <div className="panel loading-panel">正在加载会话…</div> : null}
      {query.isError ? (
        <div className="panel error-panel">
          <h2>无法加载会话</h2>
          <p>{formatError(query.error)}</p>
        </div>
      ) : null}
      {deleteMutation.isError ? (
        <div className="panel error-panel"><p>{formatError(deleteMutation.error)}</p></div>
      ) : null}
      {createMutation.isError ? (
        <div className="panel error-panel"><p>{formatError(createMutation.error)}</p></div>
      ) : null}
      {query.data?.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon" aria-hidden="true">蜂</div>
          <h2>开始第一次对话</h2>
          <p>输入目标，AgentLoom 会自动安排协作过程。</p>
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
        {query.data?.map((colony) => (
          <article className="colony-card" key={colony.id}>
            <header>
              <span className="colony-avatar">Q</span>
              <div className="card-actions">
                <span className={`status-pill status-${colony.status}`}>{statusText(colony.status)}</span>
                <button
                  aria-label={`删除会话 ${colony.name}`}
                  className="delete-button"
                  disabled={deleteMutation.isPending && deleteMutation.variables === colony.id}
                  onClick={() => removeSession(colony.id, colony.name)}
                  type="button"
                >
                  删除
                </button>
              </div>
            </header>
            <Link className="colony-card-link" to={`/colonies/${colony.id}`}>
              <h2>{colony.name}</h2>
              <p>继续这次协作对话</p>
            </Link>
            <footer>
              <span>最近更新</span><time>{formatDateTime(colony.updated_at)}</time>
            </footer>
          </article>
        ))}
      </div>
    </section>
  );
}
