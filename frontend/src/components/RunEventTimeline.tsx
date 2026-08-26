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
          <span className="eyebrow">Live activity</span>
          <h2 id="events-title">Event timeline</h2>
        </div>
        <span className={`connection-state ${connected ? "connected" : ""}`}>
          {connected ? "Live" : error ?? "Disconnected"}
        </span>
      </div>
      {events.length === 0 ? (
        <p className="muted-placeholder">Events will appear as the scheduler advances this run.</p>
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
