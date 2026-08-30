import { FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { createColony, submitMessage } from "../api/colonies";
import { formatError, sessionNameFromMessage } from "../utils/format";

export function NewColonyPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [content, setContent] = useState("");
  const mutation = useMutation({
    mutationFn: async (initialMessage: string) => {
      const colony = await createColony({
        name: sessionNameFromMessage(initialMessage),
        description: "",
        queen_profile: "general",
        settings: {},
      });
      if (!colony.queen_session_id) throw new Error("会话创建失败：缺少对话标识");
      await submitMessage(colony.queen_session_id, initialMessage);
      return colony;
    },
    onSuccess: async (colony) => {
      await queryClient.invalidateQueries({ queryKey: ["colonies"] });
      navigate(`/colonies/${colony.id}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const value = content.trim();
    if (value) mutation.mutate(value);
  }

  return (
    <section className="narrow-page" aria-labelledby="new-colony-title">
      <Link className="back-link" to="/colonies">← 返回会话列表</Link>
      <div className="new-session-hero">
        <span className="eyebrow">新建会话</span>
        <h1 id="new-colony-title">今天想完成什么？</h1>
        <p>直接描述目标即可开始。系统会自动建立会话并按需要组织多个智能体协作。</p>
      </div>
      <form className="panel new-session-form" onSubmit={submit}>
        <label className="sr-only" htmlFor="initial-message">输入第一条消息</label>
        <textarea
          autoFocus
          id="initial-message"
          onChange={(event) => setContent(event.target.value)}
          placeholder="例如：帮我对比几个适合秋季旅行的城市，并给出行程建议"
          rows={6}
          value={content}
        />
        {mutation.isError ? <div className="form-error">{formatError(mutation.error)}</div> : null}
        <button className="primary-button" disabled={!content.trim() || mutation.isPending} type="submit">
          {mutation.isPending ? "正在建立会话…" : "开始会话"}
        </button>
      </form>
    </section>
  );
}
