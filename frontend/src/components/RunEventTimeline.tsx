import type { LiveRunEvent } from "../hooks/useRunEvents";
import { humanize } from "../utils/format";

interface RunEventTimelineProps {
  events: LiveRunEvent[];
  connected: boolean;
  error: string | null;
}

export function RunEventTimeline({ events, connected, error }: RunEventTimelineProps) {
  return (
    <section className="panel event-panel" aria-labelledby="events-title">
      <div className="panel-heading compact-heading">
        <div>
          <span className="eyebrow">实时动态</span>
          <h2 id="events-title">事件时间线</h2>
        </div>
        <span className={`connection-state ${connected ? "connected" : ""}`}>
          {connected ? "实时连接" : error ?? "已断开连接"}
        </span>
      </div>
      {events.length === 0 ? (
        <p className="muted-placeholder">调度器推进运行后，事件会显示在这里。</p>
      ) : (
        <ol className="event-list">
          {[...events].reverse().map((event) => (
            <li key={event.sequence}>
              <span className="event-sequence">{event.sequence}</span>
              <div>
                <strong>{humanize(event.type)}</strong>
                <p>
                  {event.nodeKey ? `${event.nodeKey} · ` : ""}
                  {new Date(event.receivedAt).toLocaleTimeString()}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
