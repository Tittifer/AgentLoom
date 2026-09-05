import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { createQueen, listQueens, type QueenCreate } from "../api/queens";
import { formatError } from "../utils/format";

export function QueenListPage() {
  const [showCreateForm, setShowCreateForm] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["queens"], queryFn: listQueens });
  const createMutation = useMutation({
    mutationFn: createQueen,
    onSuccess: async (queen) => {
      await queryClient.invalidateQueries({ queryKey: ["queens"] });
      navigate(`/queens/${queen.id}`);
    },
  });

  function submitQueen(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload: QueenCreate = {
      id: String(form.get("id") ?? "").trim(),
      name: String(form.get("name") ?? "").trim(),
      description: String(form.get("description") ?? "").trim(),
      system_prompt: String(form.get("system_prompt") ?? "").trim(),
      default_model: String(form.get("default_model") ?? "").trim(),
      settings: {},
    };
    createMutation.mutate(payload);
  }

  function toggleCreateForm() {
    createMutation.reset();
    setShowCreateForm((visible) => !visible);
  }

  return (
    <section aria-labelledby="queens-title">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Queen 管理</span>
          <h1 id="queens-title">选择 Queen</h1>
          <p>每个 Queen 共享身份和工具配置，旗下会话保持相互隔离。</p>
        </div>
        <button className="primary-button" onClick={toggleCreateForm} type="button">
          {showCreateForm ? "取消创建" : "新建 Queen"}
        </button>
      </div>
      {showCreateForm ? (
        <form className="panel queen-create-panel" onSubmit={submitQueen}>
          <div className="panel-title-row">
            <div>
              <span className="eyebrow">身份配置</span>
              <h2>创建 Queen</h2>
              <p>Queen 身份由旗下会话共享，但每条会话仍独立运行。</p>
            </div>
          </div>
          <div className="queen-form-grid">
            <label className="form-field">
              <span>唯一 ID</span>
              <input
                disabled={createMutation.isPending}
                maxLength={100}
                name="id"
                pattern="[a-z0-9][a-z0-9_-]{0,99}"
                placeholder="例如 research"
                required
              />
              <small>仅支持小写字母、数字、下划线和连字符。</small>
            </label>
            <label className="form-field">
              <span>名称</span>
              <input disabled={createMutation.isPending} maxLength={100} name="name" required />
            </label>
            <label className="form-field queen-form-wide">
              <span>描述</span>
              <input disabled={createMutation.isPending} maxLength={1000} name="description" />
            </label>
            <label className="form-field queen-form-wide">
              <span>系统提示词</span>
              <textarea disabled={createMutation.isPending} maxLength={20000} name="system_prompt" rows={4} />
            </label>
            <label className="form-field queen-form-wide">
              <span>默认模型</span>
              <input
                defaultValue={query.data?.find((queen) => queen.id === "general")?.default_model ?? ""}
                disabled={createMutation.isPending}
                maxLength={200}
                name="default_model"
                placeholder="例如 openai/deepseek-v4-flash"
                required
              />
            </label>
          </div>
          {createMutation.isError ? (
            <div className="form-error" role="alert">{formatError(createMutation.error)}</div>
          ) : null}
          <div className="form-actions">
            <button
              className="secondary-button"
              disabled={createMutation.isPending}
              onClick={toggleCreateForm}
              type="button"
            >
              取消
            </button>
            <button className="primary-button" disabled={createMutation.isPending} type="submit">
              {createMutation.isPending ? "正在创建…" : "创建 Queen"}
            </button>
          </div>
        </form>
      ) : null}
      {query.isLoading ? <div className="panel loading-panel">正在加载 Queen…</div> : null}
      {query.isError ? (
        <div className="panel error-panel"><p>{formatError(query.error)}</p></div>
      ) : null}
      <div className="colony-card-grid">
        {query.data?.map((queen) => (
          <article className="colony-card" key={queen.id}>
            <header><span className="colony-avatar">Q</span></header>
            <Link className="colony-card-link" to={`/queens/${queen.id}`}>
              <h2>{queen.name}</h2>
              <p>{queen.description || "查看该 Queen 的会话"}</p>
            </Link>
            <footer><span>默认模型</span><span>{queen.default_model}</span></footer>
          </article>
        ))}
      </div>
    </section>
  );
}
