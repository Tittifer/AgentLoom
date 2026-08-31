import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import {
  createColony,
  deleteColony,
  getColony,
  listColonies,
  listMessages,
  submitMessage,
  type WorkerRead,
} from "../api/colonies";
import { ChatPanel } from "../components/ChatPanel";
import { ColonySidebar } from "../components/ColonySidebar";
import { SessionNavigation } from "../components/SessionNavigation";
import { WorkerDrawer } from "../components/WorkerDrawer";
import { useColonyEvents } from "../hooks/useColonyEvents";
import { formatError, statusText } from "../utils/format";

export function ColonyWorkspacePage() {
  const { colonyId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selectedWorker, setSelectedWorker] = useState<WorkerRead | null>(null);
  const coloniesQuery = useQuery({ queryKey: ["colonies"], queryFn: listColonies });
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
  const streamingMessage = useColonyEvents(
    colonyId,
    queenId,
    (messagesQuery.data ?? []).map((message) => message.id),
  );

  if (colonyQuery.isLoading) return <div className="panel loading-panel">正在进入会话…</div>;
  if (colonyQuery.isError || !colonyQuery.data) {
    return <div className="panel error-panel"><h2>无法打开会话</h2><p>{formatError(colonyQuery.error)}</p></div>;
  }
  const snapshot = colonyQuery.data;
  const activeWorkerCount = snapshot.workers.filter((worker) =>
    ["queued", "running", "reporting"].includes(worker.status)
  ).length;

  return (
    <section className="workspace-page" aria-labelledby="workspace-title">
      <div className="workspace-shell">
        <SessionNavigation
          colonies={coloniesQuery.data ?? [snapshot.colony]}
          creating={createMutation.isPending}
          onCreate={() => createMutation.mutate()}
        />
        <div className="conversation-workspace">
          <header className="workspace-heading">
            <div>
              <span className="eyebrow">协作会话</span>
              <h1 id="workspace-title">{snapshot.colony.name}</h1>
            </div>
            <div className="workspace-actions">
              <span className={`status-pill status-${snapshot.colony.status}`}>
                {statusText(snapshot.colony.status)}
              </span>
              <span className="worker-count-label">{activeWorkerCount} 个 Worker 运行中</span>
              <button
                className="workspace-delete-button"
                disabled={deleteMutation.isPending}
                onClick={() => {
                  if (window.confirm(`确定删除会话“${snapshot.colony.name}”吗？删除后无法恢复。`)) {
                    deleteMutation.mutate();
                  }
                }}
                type="button"
              >
                {deleteMutation.isPending ? "删除中…" : "删除"}
              </button>
            </div>
          </header>
          {deleteMutation.isError ? <div className="form-error">{formatError(deleteMutation.error)}</div> : null}
          {createMutation.isError ? <div className="form-error">{formatError(createMutation.error)}</div> : null}
          <ChatPanel
            activeWorkerCount={activeWorkerCount}
            messages={messagesQuery.data ?? []}
            onSend={async (content) => { await messageMutation.mutateAsync(content); }}
            sending={messageMutation.isPending}
            session={snapshot.queen_session}
            streamingMessage={streamingMessage}
          />
        </div>
        <ColonySidebar
          onSelectWorker={setSelectedWorker}
          queen={snapshot.queen_session}
          tasks={snapshot.tasks}
          tracker={snapshot.tracker}
          workers={snapshot.workers}
        />
      </div>
      <WorkerDrawer onClose={() => setSelectedWorker(null)} worker={selectedWorker} />
    </section>
  );
}

function requireId(value: string | undefined): string {
  if (!value) throw new Error("缺少资源标识");
  return value;
}
