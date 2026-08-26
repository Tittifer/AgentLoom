import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getNodeAttempts, getNodeMessages, type NodeRunRead } from "../api/runs";
import type { WorkflowNodeRead } from "../api/tasks";
import { formatDate, formatError, formatJson, humanize } from "../utils/format";

interface NodeDetailDrawerProps {
  runId: string;
  node: WorkflowNodeRead;
  latestNodeRun?: NodeRunRead;
  onClose: () => void;
}

interface JsonSectionProps {
  title: string;
  value: NodeRunRead["input"] | null;
}

function JsonSection({ title, value }: JsonSectionProps) {
  if (value === null) {
    return null;
  }
  return (
    <section className="drawer-section">
      <h3>{title}</h3>
      <pre>{formatJson(value)}</pre>
    </section>
  );
}

export function NodeDetailDrawer({
  runId,
  node,
  latestNodeRun,
  onClose,
}: NodeDetailDrawerProps) {
  const [selectedAttemptId, setSelectedAttemptId] = useState<string>();
  const attemptsQuery = useQuery({
    queryKey: ["node-attempts", runId, node.key],
    queryFn: () => getNodeAttempts(runId, node.key),
  });

  const attempts = attemptsQuery.data ?? (latestNodeRun ? [latestNodeRun] : []);
  const attempt =
    attempts.find((item) => item.id === selectedAttemptId) ?? attempts.at(-1) ?? latestNodeRun;
  const messagesQuery = useQuery({
    queryKey: ["node-messages", attempt?.id],
    queryFn: () => getNodeMessages(attempt?.id ?? ""),
    enabled: Boolean(attempt?.id),
  });

  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        aria-labelledby="node-detail-title"
        className="node-drawer"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="drawer-header">
          <div>
            <span className="eyebrow">{node.role}</span>
            <h2 id="node-detail-title">{node.name}</h2>
          </div>
          <button aria-label="Close node details" className="icon-button" onClick={onClose} type="button">
            ×
          </button>
        </header>

        <p>{node.description}</p>
        <dl className="definition-list">
          <div><dt>Key</dt><dd>{node.key}</dd></div>
          <div><dt>Depends on</dt><dd>{node.depends_on.join(", ") || "None"}</dd></div>
          <div><dt>Tools</dt><dd>{node.tools.join(", ") || "None"}</dd></div>
          <div><dt>Review criteria</dt><dd>{node.review_criteria ?? "Schema validation only"}</dd></div>
        </dl>

        <section className="drawer-section">
          <h3>Attempts</h3>
          {attemptsQuery.isError ? <p className="error-message">{formatError(attemptsQuery.error)}</p> : null}
          <div className="attempt-tabs">
            {attempts.map((item) => (
              <button
                className={attempt?.id === item.id ? "active" : ""}
                key={item.id}
                onClick={() => setSelectedAttemptId(item.id)}
                type="button"
              >
                #{item.attempt} · {humanize(item.status)}
              </button>
            ))}
          </div>
        </section>

        {attempt ? (
          <>
            <dl className="definition-list compact-list">
              <div><dt>Status</dt><dd>{humanize(attempt.status)}</dd></div>
              <div><dt>Started</dt><dd>{formatDate(attempt.started_at)}</dd></div>
              <div><dt>Ended</dt><dd>{formatDate(attempt.ended_at)}</dd></div>
            </dl>
            <JsonSection title="Input" value={attempt.input} />
            <JsonSection title="Output" value={attempt.output} />
            <JsonSection title="Reviewer" value={attempt.review} />
            <JsonSection title="Token usage" value={attempt.usage} />
            <JsonSection title="Error" value={attempt.error} />

            <section className="drawer-section">
              <h3>Agent-visible messages</h3>
              {messagesQuery.isLoading ? <p>Loading messages…</p> : null}
              {messagesQuery.isError ? <p className="error-message">{formatError(messagesQuery.error)}</p> : null}
              <div className="message-list">
                {messagesQuery.data?.map((message) => (
                  <article key={message.id}>
                    <header>
                      <strong>{message.role}</strong>
                      <time>{formatDate(message.created_at)}</time>
                    </header>
                    <pre>{message.content || formatJson(message.tool_calls)}</pre>
                  </article>
                ))}
              </div>
            </section>
          </>
        ) : (
          <p className="muted-placeholder">No attempt has been created for this node.</p>
        )}

        <section className="drawer-section">
          <h3>Output schema</h3>
          <pre>{formatJson(node.output_schema)}</pre>
        </section>
      </aside>
    </div>
  );
}
