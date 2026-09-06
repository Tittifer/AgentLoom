import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { deleteMemory, getMemory, listMemories, updateMemory, type Memory } from "../api/memories";
import { listQueens } from "../api/queens";
import { formatError } from "../utils/format";

export function MemoryLibraryPage() {
  const [scope, setScope] = useState<"global" | "queen">("global");
  const [queenId, setQueenId] = useState("");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const memories = useQuery({ queryKey: ["memories"], queryFn: listMemories });
  const queens = useQuery({ queryKey: ["queens"], queryFn: listQueens });
  const detail = useQuery({
    queryKey: ["memory", selectedPath],
    queryFn: () => getMemory(selectedPath!),
    enabled: selectedPath !== null,
  });

  const effectiveQueenId = queenId || queens.data?.[0]?.id || "";

  const visible = useMemo(
    () =>
      (memories.data ?? []).filter((memory) =>
        scope === "global" ? memory.scope === "global" : memory.scope === "queen" && memory.queen_id === effectiveQueenId,
      ),
    [effectiveQueenId, memories.data, scope],
  );

  return (
    <section aria-labelledby="memory-title">
      <div className="page-heading">
        <div><span className="eyebrow">长期上下文</span><h1 id="memory-title">记忆库</h1><p>查看和维护 Queen 从对话中提炼的长期记忆。</p></div>
      </div>
      <div className="memory-toolbar panel">
        <div className="memory-tabs" role="tablist">
          <button className={scope === "global" ? "active" : ""} onClick={() => { setScope("global"); setSelectedPath(null); }} type="button">全局记忆</button>
          <button className={scope === "queen" ? "active" : ""} onClick={() => { setScope("queen"); setSelectedPath(null); }} type="button">Queen 记忆</button>
        </div>
        {scope === "queen" ? (
          <label className="form-field"><span>Queen</span><select value={effectiveQueenId} onChange={(event) => { setQueenId(event.target.value); setSelectedPath(null); }}>
            {(queens.data ?? []).map((queen) => <option key={queen.id} value={queen.id}>{queen.name}</option>)}
          </select></label>
        ) : null}
      </div>
      {memories.isError ? <div className="panel error-panel">{formatError(memories.error)}</div> : null}
      <div className="memory-layout">
        <div className="panel memory-list">
          {memories.isLoading ? <p>正在加载记忆…</p> : null}
          {!memories.isLoading && visible.length === 0 ? <p className="empty-copy">当前作用域还没有记忆。</p> : null}
          {visible.map((memory) => (
            <button className={selectedPath === memory.path ? "active" : ""} key={memory.path} onClick={() => setSelectedPath(memory.path)} type="button">
              <strong>{memory.name || memory.filename}</strong><small>{memory.description || memory.filename}</small><span>{memory.type || "unknown"}</span>
            </button>
          ))}
        </div>
        <div className="panel memory-editor">
          {!selectedPath ? <p className="empty-copy">选择一条记忆查看内容。</p> : null}
          {detail.isLoading ? <p>正在读取记忆…</p> : null}
          {detail.isError ? <div className="form-error">{formatError(detail.error)}</div> : null}
          {detail.data ? <MemoryEditor key={detail.data.path} memory={detail.data} onDeleted={() => setSelectedPath(null)} /> : null}
        </div>
      </div>
    </section>
  );
}

function MemoryEditor({ memory, onDeleted }: { memory: Memory; onDeleted: () => void }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(memory.content ?? "");
  const saveMutation = useMutation({
    mutationFn: () => updateMemory(memory.path, draft),
    onSuccess: async (updated) => {
      await queryClient.invalidateQueries({ queryKey: ["memories"] });
      queryClient.setQueryData(["memory", memory.path], updated);
    },
  });
  const deleteMutation = useMutation({
    mutationFn: () => deleteMemory(memory.path),
    onSuccess: async () => {
      onDeleted();
      await queryClient.invalidateQueries({ queryKey: ["memories"] });
    },
  });
  return <>
    <header><div><h2>{memory.name || memory.filename}</h2><small>{memory.path}</small></div>
      <button className="danger-button" disabled={deleteMutation.isPending} onClick={() => { if (window.confirm("确定删除这条记忆吗？")) deleteMutation.mutate(); }} type="button">删除</button></header>
    <textarea aria-label="记忆内容" maxLength={4096} onChange={(event) => setDraft(event.target.value)} rows={18} value={draft} />
    {saveMutation.isError ? <div className="form-error">{formatError(saveMutation.error)}</div> : null}
    <div className="form-actions"><button className="primary-button" disabled={saveMutation.isPending || !draft.trim() || draft === memory.content} onClick={() => saveMutation.mutate()} type="button">{saveMutation.isPending ? "正在保存…" : "保存"}</button></div>
  </>;
}
