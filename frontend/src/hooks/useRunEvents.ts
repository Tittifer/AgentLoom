import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { JsonObject } from "../api/tasks";

const RUN_EVENT_TYPES = [
  "run.started",
  "run.completed",
  "run.failed",
  "node.started",
  "node.reviewed",
  "node.retrying",
  "node.completed",
  "node.failed",
  "llm.usage_recorded",
] as const;

export interface LiveRunEvent {
  sequence: number;
  type: string;
  nodeKey: string | null;
  payload: JsonObject;
  receivedAt: number;
}

export function useRunEvents(runId: string | undefined, enabled: boolean) {
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<LiveRunEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEvents([]);
  }, [runId]);

  useEffect(() => {
    if (!runId || !enabled) {
      setConnected(false);
      return;
    }

    const source = new EventSource(`/api/runs/${runId}/events?after=0`);
    const listeners = new Map<string, EventListener>();
    source.onopen = () => {
      setConnected(true);
      setError(null);
    };
    source.onerror = () => {
      setConnected(false);
      setError("Reconnecting");
    };

    RUN_EVENT_TYPES.forEach((type) => {
      const listener: EventListener = (rawEvent) => {
        const event = rawEvent as MessageEvent<string>;
        let payload: JsonObject;
        try {
          payload = JSON.parse(event.data) as JsonObject;
        } catch {
          setError("Received an invalid event payload");
          source.close();
          return;
        }
        const sequence = Number(event.lastEventId);
        if (!Number.isFinite(sequence)) {
          setError("Received an event without a valid sequence");
          source.close();
          return;
        }
        const nodeKey = typeof payload.node_key === "string" ? payload.node_key : null;
        setEvents((current) => {
          if (current.some((item) => item.sequence === sequence)) {
            return current;
          }
          return [...current, { sequence, type, nodeKey, payload, receivedAt: Date.now() }].slice(
            -100,
          );
        });
        void queryClient.invalidateQueries({ queryKey: ["run", runId] });
        if (type === "run.completed" || type === "run.failed") {
          source.close();
          setConnected(false);
          setError("Run finished");
        }
      };
      listeners.set(type, listener);
      source.addEventListener(type, listener);
    });

    return () => {
      listeners.forEach((listener, type) => source.removeEventListener(type, listener));
      source.close();
      setConnected(false);
    };
  }, [enabled, queryClient, runId]);

  return { events, connected, error };
}
