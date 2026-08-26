import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { JsonObject } from "../api/tasks";

const RUN_EVENT_TYPES = [
  "run.started",
  "run.recovered",
  "run.completed",
  "run.failed",
  "run.cancelled",
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
  const [eventState, setEventState] = useState<{
    runId: string | undefined;
    events: LiveRunEvent[];
  }>({ runId, events: [] });
  const [connectionState, setConnectionState] = useState<{
    runId: string | undefined;
    connected: boolean;
    error: string | null;
  }>({ runId, connected: false, error: null });

  useEffect(() => {
    if (!runId || !enabled) {
      return;
    }

    const source = new EventSource(`/api/runs/${runId}/events?after=0`);
    const listeners = new Map<string, EventListener>();
    source.onopen = () => {
      setConnectionState({ runId, connected: true, error: null });
    };
    source.onerror = () => {
      setConnectionState({ runId, connected: false, error: "Reconnecting" });
    };

    RUN_EVENT_TYPES.forEach((type) => {
      const listener: EventListener = (rawEvent) => {
        const event = rawEvent as MessageEvent<string>;
        let payload: JsonObject;
        try {
          payload = JSON.parse(event.data) as JsonObject;
        } catch {
          setConnectionState({
            runId,
            connected: false,
            error: "Received an invalid event payload",
          });
          source.close();
          return;
        }
        const sequence = Number(event.lastEventId);
        if (!Number.isFinite(sequence)) {
          setConnectionState({
            runId,
            connected: false,
            error: "Received an event without a valid sequence",
          });
          source.close();
          return;
        }
        const nodeKey = typeof payload.node_key === "string" ? payload.node_key : null;
        setEventState((current) => {
          const events = current.runId === runId ? current.events : [];
          if (events.some((item) => item.sequence === sequence)) {
            return { runId, events };
          }
          return {
            runId,
            events: [...events, { sequence, type, nodeKey, payload, receivedAt: Date.now() }].slice(
              -100,
            ),
          };
        });
        void queryClient.invalidateQueries({ queryKey: ["run", runId] });
        if (type === "run.completed" || type === "run.failed" || type === "run.cancelled") {
          source.close();
          setConnectionState({ runId, connected: false, error: "Run finished" });
        }
      };
      listeners.set(type, listener);
      source.addEventListener(type, listener);
    });

    return () => {
      listeners.forEach((listener, type) => source.removeEventListener(type, listener));
      source.close();
    };
  }, [enabled, queryClient, runId]);

  return {
    events: eventState.runId === runId ? eventState.events : [],
    connected: connectionState.runId === runId && connectionState.connected,
    error: connectionState.runId === runId ? connectionState.error : null,
  };
}
