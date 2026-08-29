import { FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { createColony } from "../api/colonies";
import { formatError } from "../utils/format";

export function NewColonyPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [profile, setProfile] = useState("general");
  const mutation = useMutation({
    mutationFn: createColony,
    onSuccess: async (colony) => {
      await queryClient.invalidateQueries({ queryKey: ["colonies"] });
      navigate(`/colonies/${colony.id}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    mutation.mutate({
      name,
      description,
      queen_profile: profile,
      settings: {},
    });
  }

  return (
    <section className="narrow-page" aria-labelledby="new-colony-title">
      <Link className="back-link" to="/colonies">← 返回协作空间</Link>
      <div className="page-heading">
        <div>
          <span className="eyebrow">NEW COLONY</span>
          <h1 id="new-colony-title">创建 Colony</h1>
          <p>创建后即可直接向 Queen 发送目标，不再需要预先编排固定 DAG。</p>
        </div>
      </div>
      <form className="panel colony-form" onSubmit={submit}>
        <label>
          <span>名称</span>
          <input maxLength={200} onChange={(event) => setName(event.target.value)} required value={name} />
        </label>
        <label>
          <span>说明</span>
          <textarea onChange={(event) => setDescription(event.target.value)} rows={5} value={description} />
        </label>
        <label>
          <span>Queen 配置</span>
          <select onChange={(event) => setProfile(event.target.value)} value={profile}>
            <option value="general">通用协作</option>
            <option value="research">深度研究</option>
            <option value="engineering">工程实现</option>
          </select>
        </label>
        {mutation.isError ? <div className="form-error">{formatError(mutation.error)}</div> : null}
        <div className="form-actions">
          <Link className="secondary-button button-link" to="/colonies">取消</Link>
          <button className="primary-button" disabled={!name.trim() || mutation.isPending} type="submit">
            {mutation.isPending ? "创建中…" : "创建并进入工作台"}
          </button>
        </div>
      </form>
    </section>
  );
}
