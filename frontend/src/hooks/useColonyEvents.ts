import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

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

export interface StreamingAssistantMessage {
  id: string;
  content: string;
}

interface ActiveStreamingMessage extends StreamingAssistantMessage {
  sessionId: string;
}

interface MessageDeltaEvent {
  session_id: string;
  message_id: string;
  delta: string;
}

export function useColonyEvents(
  colonyId: string | undefined,
  queenSessionId?: string,
  persistedMessageIds: readonly string[] = [],
) {
  const queryClient = useQueryClient();
  const [streamingMessage, setStreamingMessage] = useState<ActiveStreamingMessage | null>(null);

  useEffect(() => {
    if (!colonyId) return undefined;
    const source = new EventSource(`/api/colonies/${colonyId}/events?after=0`);

    const listeners = EVENT_TYPES.map((type) => {
      const listener = () => {
        void queryClient.invalidateQueries({ queryKey: ["colony", colonyId] });
        if (queenSessionId) {
          void queryClient.invalidateQueries({ queryKey: ["messages", queenSessionId] });
        }
      };
      source.addEventListener(type, listener);
      return [type, listener] as const;
    });

    const deltaListener = (event: Event) => {
      const data = parseDeltaEvent(event);
      if (!data || data.session_id !== queenSessionId) return;
      setStreamingMessage((current) => ({
        id: data.message_id,
        sessionId: data.session_id,
        content: current?.id === data.message_id
          ? current.content + data.delta
          : data.delta,
      }));
    };
    const cancelListener = (event: Event) => {
      const data = parseDeltaEvent(event, false);
      if (!data || data.session_id !== queenSessionId) return;
      setStreamingMessage((current) => current?.id === data.message_id ? null : current);
    };
    source.addEventListener("message.delta", deltaListener);
    source.addEventListener("message.stream.cancelled", cancelListener);

    return () => {
      listeners.forEach(([type, listener]) => source.removeEventListener(type, listener));
      source.removeEventListener("message.delta", deltaListener);
      source.removeEventListener("message.stream.cancelled", cancelListener);
      source.close();
    };
  }, [colonyId, queenSessionId, queryClient]);

  if (!streamingMessage) return null;
  if (
    streamingMessage.sessionId !== queenSessionId ||
    persistedMessageIds.includes(streamingMessage.id)
  ) return null;
  return { id: streamingMessage.id, content: streamingMessage.content };
}

function parseDeltaEvent(event: Event, requireDelta = true): MessageDeltaEvent | null {
  if (!(event instanceof MessageEvent) || typeof event.data !== "string") return null;
  try {
    const data: unknown = JSON.parse(event.data);
    if (!isRecord(data)) return null;
    if (
      typeof data.session_id !== "string" ||
      typeof data.message_id !== "string" ||
      (requireDelta && typeof data.delta !== "string")
    ) return null;
    return {
      session_id: data.session_id,
      message_id: data.message_id,
      delta: typeof data.delta === "string" ? data.delta : "",
    };
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
