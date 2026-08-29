import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { getColony, listMessages, submitMessage, type WorkerRead } from "../api/colonies";
import { ChatPanel } from "../components/ChatPanel";
import { ColonyEventStrip } from "../components/ColonyEventStrip";
import { ColonySidebar } from "../components/ColonySidebar";
import { WorkerDrawer } from "../components/WorkerDrawer";
import { WorkerMap } from "../components/WorkerMap";
import { useColonyEvents } from "../hooks/useColonyEvents";
import { formatError } from "../utils/format";

export function ColonyWorkspacePage() {
  const { colonyId } = useParams();
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
  const eventStream = useColonyEvents(colonyId, queenId);

  if (colonyQuery.isLoading) return <div className="panel loading-panel">正在进入 Colony…</div>;
  if (colonyQuery.isError || !colonyQuery.data) {
    return <div className="panel error-panel"><h2>无法打开 Colony</h2><p>{formatError(colonyQuery.error)}</p></div>;
  }
  const snapshot = colonyQuery.data;

  return (
    <section className="workspace-page" aria-labelledby="workspace-title">
      <div className="workspace-heading">
        <div>
          <Link className="back-link" to="/colonies">← 协作空间</Link>
          <span className="eyebrow">COLONY WORKSPACE</span>
          <h1 id="workspace-title">{snapshot.colony.name}</h1>
          <p>{snapshot.colony.description || "与 Queen 持续协作，动态调度 Worker 完成目标。"}</p>
        </div>
        <div className="model-chip"><small>当前模型</small><strong>{snapshot.colony.model}</strong></div>
      </div>
      <ColonyEventStrip connected={eventStream.connected} events={eventStream.events} />
      <div className="workspace-grid">
        <div className="workspace-main">
          <WorkerMap queen={snapshot.queen_session} workers={snapshot.workers} onSelect={setSelectedWorker} />
          <ChatPanel
            messages={messagesQuery.data ?? []}
            onSend={async (content) => { await messageMutation.mutateAsync(content); }}
            sending={messageMutation.isPending}
            session={snapshot.queen_session}
          />
        </div>
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
