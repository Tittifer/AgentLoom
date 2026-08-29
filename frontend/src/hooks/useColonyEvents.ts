import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

export interface ColonyUiEvent {
  id: number;
  type: string;
  data: Record<string, unknown>;
}

const EVENT_TYPES = [
  "colony.created",
  "message.created",
  "message.completed",
  "session.started",
  "session.idle",
  "session.failed",
  "worker.queued",
  "worker.started",
  "worker.reported",
  "worker.timed_out",
  "tool.completed",
  "judge.reviewed",
  "tracker.updated",
  "task.created",
  "task.updated",
] as const;

export function useColonyEvents(colonyId: string | undefined, queenSessionId?: string) {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<ColonyUiEvent[]>([]);

  useEffect(() => {
    if (!colonyId) return;
    const source = new EventSource(`/api/colonies/${colonyId}/events?after=0`);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);

    const listeners = EVENT_TYPES.map((type) => {
      const listener = (raw: Event) => {
        const event = raw as MessageEvent<string>;
        const parsed = JSON.parse(event.data) as Record<string, unknown>;
        setEvents((current) => [
          ...current.slice(-99),
          { id: Number(event.lastEventId || 0), type, data: parsed },
        ]);
        void queryClient.invalidateQueries({ queryKey: ["colony", colonyId] });
        if (queenSessionId) {
          void queryClient.invalidateQueries({ queryKey: ["messages", queenSessionId] });
        }
      };
      source.addEventListener(type, listener);
      return [type, listener] as const;
    });

    return () => {
      listeners.forEach(([type, listener]) => source.removeEventListener(type, listener));
      source.close();
    };
  }, [colonyId, queenSessionId, queryClient]);

  return { connected, events };
}
