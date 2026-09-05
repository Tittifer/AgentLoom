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
      name: String(form.get("name") ?? "").trim(),
      description: String(form.get("description") ?? "").trim(),
      system_prompt: String(form.get("system_prompt") ?? "").trim(),
      model: String(form.get("model") ?? "").trim(),
      base_url: String(form.get("base_url") ?? "").trim(),
      api_key: String(form.get("api_key") ?? "").trim(),
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
              <span>名称</span>
              <input disabled={createMutation.isPending} maxLength={100} name="name" required />
            </label>
            <label className="form-field">
              <span>描述</span>
              <input disabled={createMutation.isPending} maxLength={1000} name="description" />
            </label>
            <label className="form-field queen-form-wide">
              <span>系统提示词</span>
              <textarea disabled={createMutation.isPending} maxLength={20000} name="system_prompt" rows={4} />
            </label>
            <label className="form-field queen-form-wide">
              <span>模型名称</span>
              <input
                disabled={createMutation.isPending}
                maxLength={200}
                name="model"
                placeholder="例如 deepseek-v4-flash、claude-sonnet-4 或 gemini-2.5-pro"
                required
              />
              <small>后端将根据模型名称自动选择 OpenAI、Claude 或 Gemini 协议。</small>
            </label>
            <label className="form-field queen-form-wide">
              <span>服务 Base URL</span>
              <input
                disabled={createMutation.isPending}
                maxLength={2000}
                name="base_url"
                placeholder="例如 https://api.example.com"
                required
                type="url"
              />
              <small>只填写服务根地址，不要添加 /v1、/messages 等接口后缀。</small>
            </label>
            <label className="form-field queen-form-wide">
              <span>API Key</span>
              <input
                autoComplete="new-password"
                disabled={createMutation.isPending}
                maxLength={10000}
                name="api_key"
                required
                type="password"
              />
              <small>密钥仅写入本机 Queen YAML，不会通过 Queen 查询接口返回。</small>
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
            <footer><span>{queen.protocol} 协议</span><span>{queen.model}</span></footer>
          </article>
        ))}
      </div>
    </section>
  );
}
