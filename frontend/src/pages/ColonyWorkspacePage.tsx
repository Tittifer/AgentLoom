import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import { deleteColony, getColony, listMessages, submitMessage, type WorkerRead } from "../api/colonies";
import { ChatPanel } from "../components/ChatPanel";
import { ColonySidebar } from "../components/ColonySidebar";
import { WorkerDrawer } from "../components/WorkerDrawer";
import { WorkerMap } from "../components/WorkerMap";
import { useColonyEvents } from "../hooks/useColonyEvents";
import { formatError } from "../utils/format";

export function ColonyWorkspacePage() {
  const { colonyId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selectedWorker, setSelectedWorker] = useState<WorkerRead | null>(null);
  const colonyQuery = useQuery({
    queryKey: ["colony", colonyId],
    queryFn: () => getColony(requireId(colonyId)),
    enabled: Boolean(colonyId),
    refetchInterval: 10_000,
  });
  const queenId = colonyQuery.data?.queen_session.id;
  const messagesQuery = useQuery({
    queryKey: ["messages", queenId],
    queryFn: () => listMessages(requireId(queenId)),
    enabled: Boolean(queenId),
  });
  const messageMutation = useMutation({
    mutationFn: (content: string) => submitMessage(requireId(queenId), content),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["messages", queenId] }),
        queryClient.invalidateQueries({ queryKey: ["colony", colonyId] }),
      ]);
    },
  });
  const deleteMutation = useMutation({
    mutationFn: () => deleteColony(requireId(colonyId)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["colonies"] });
      navigate("/colonies");
    },
  });
  useColonyEvents(colonyId, queenId);

  if (colonyQuery.isLoading) return <div className="panel loading-panel">正在进入会话…</div>;
  if (colonyQuery.isError || !colonyQuery.data) {
    return <div className="panel error-panel"><h2>无法打开会话</h2><p>{formatError(colonyQuery.error)}</p></div>;
  }
  const snapshot = colonyQuery.data;

  return (
    <section className="workspace-page" aria-labelledby="workspace-title">
      <div className="workspace-heading">
        <div>
          <Link className="back-link" to="/colonies">← 会话列表</Link>
          <span className="eyebrow">协作会话</span>
          <h1 id="workspace-title">{snapshot.colony.name}</h1>
          <p>你只需要持续对话，任务拆解与智能体协作会在后台自动完成。</p>
        </div>
        <div className="workspace-actions">
          <button
            className="danger-button"
            disabled={deleteMutation.isPending}
            onClick={() => {
              if (window.confirm(`确定删除会话“${snapshot.colony.name}”吗？删除后无法恢复。`)) {
                deleteMutation.mutate();
              }
            }}
            type="button"
          >
            {deleteMutation.isPending ? "正在删除…" : "删除会话"}
          </button>
        </div>
      </div>
      {deleteMutation.isError ? <div className="form-error">{formatError(deleteMutation.error)}</div> : null}
      <WorkerMap queen={snapshot.queen_session} workers={snapshot.workers} onSelect={setSelectedWorker} />
      <div className="workspace-grid">
        <ChatPanel
          messages={messagesQuery.data ?? []}
          onSend={async (content) => { await messageMutation.mutateAsync(content); }}
          sending={messageMutation.isPending}
          session={snapshot.queen_session}
        />
        <ColonySidebar tasks={snapshot.tasks} tracker={snapshot.tracker} />
      </div>
      <WorkerDrawer onClose={() => setSelectedWorker(null)} worker={selectedWorker} />
    </section>
  );
}

function requireId(value: string | undefined): string {
  if (!value) throw new Error("缺少资源标识");
  return value;
}
