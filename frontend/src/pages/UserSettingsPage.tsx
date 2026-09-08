import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent } from "react";

import {
  getUserSettings,
  updateUserSettings,
  type UserSettingsUpdate,
} from "../api/settings";
import { formatError } from "../utils/format";

export function UserSettingsPage() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["user-settings"], queryFn: getUserSettings });
  const mutation = useMutation({
    mutationFn: updateUserSettings,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["user-settings"] });
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload: UserSettingsUpdate = {
      model: String(form.get("model") ?? "").trim(),
      base_url: String(form.get("base_url") ?? "").trim(),
      api_key: String(form.get("api_key") ?? "").trim(),
      response_format: String(form.get("response_format")) as UserSettingsUpdate["response_format"],
      max_context_tokens: Number(form.get("max_context_tokens") ?? 128000),
    };
    mutation.mutate(payload);
  }

  return (
    <section aria-labelledby="settings-title">
      <div className="page-heading settings-heading">
        <div>
          <span className="eyebrow">用户设置</span>
          <h1 id="settings-title">LLM 配置</h1>
          <p>所有 Queen、Colony 和 Worker 共用这一套本地模型配置。</p>
        </div>
        <span className={`settings-state ${query.data?.configured ? "configured" : ""}`}>
          {query.data?.configured ? "已配置" : "未配置"}
        </span>
      </div>

      {query.isLoading ? <div className="panel loading-panel">正在读取设置…</div> : null}
      {query.isError ? <div className="panel error-panel">{formatError(query.error)}</div> : null}
      {query.data ? (
        <form className="panel user-settings-form" key={query.data.updated_at ?? "empty"} onSubmit={submit}>
          <header>
            <div><h2>模型服务</h2><p>协议将根据模型名称自动选择，Base URL 不要包含接口后缀。</p></div>
            {query.data.protocol ? <span className="protocol-chip">{query.data.protocol}</span> : null}
          </header>
          <div className="queen-form-grid">
            <label className="form-field queen-form-wide">
              <span>模型名称</span>
              <input defaultValue={query.data.model ?? ""} name="model" placeholder="例如 deepseek-v4-flash" required />
            </label>
            <label className="form-field queen-form-wide">
              <span>服务 Base URL</span>
              <input defaultValue={query.data.base_url ?? ""} name="base_url" placeholder="https://api.example.com" required type="url" />
              <small>仅填写服务根地址，不要添加 /v1、/messages 等后缀。</small>
            </label>
            <label className="form-field queen-form-wide">
              <span>API Key</span>
              <input autoComplete="new-password" name="api_key" placeholder={query.data.api_key_configured ? "重新输入 API Key 以保存" : "输入 API Key"} required type="password" />
              <small>密钥只写入本机 .agentloom/settings.yaml，读取接口不会返回密钥。</small>
            </label>
            <label className="form-field">
              <span>响应格式</span>
              <select defaultValue={query.data.response_format} name="response_format">
                <option value="json_schema">JSON Schema</option>
                <option value="json_object">JSON Object</option>
              </select>
            </label>
            <label className="form-field">
              <span>上下文窗口（tokens）</span>
              <input defaultValue={query.data.max_context_tokens} max={2000000} min={4096} name="max_context_tokens" required type="number" />
            </label>
          </div>
          {mutation.isError ? <div className="form-error" role="alert">{formatError(mutation.error)}</div> : null}
          {mutation.isSuccess ? <div className="settings-success" role="status">全局 LLM 设置已保存。</div> : null}
          <div className="form-actions">
            <button className="primary-button" disabled={mutation.isPending} type="submit">
              {mutation.isPending ? "保存中…" : "保存设置"}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
