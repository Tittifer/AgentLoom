import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

const EVENT_TYPES = [
  "colony.created",
  "colony.suggested",
  "colony.suggestion.dismissed",
  "session.created",
  "message.created",
  "message.completed",
  "session.started",
  "session.idle",
  "session.parked",
  "session.failed",
  "llm.retrying",
  "llm.retry_exhausted",
  "worker.queued",
  "worker.started",
  "worker.soft_timeout",
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

export interface LLMRetryState {
  category: string;
  attempt: number;
  maxRetries: number | null;
  delaySeconds: number;
}

export interface AgentEventState {
  streamingMessage: StreamingAssistantMessage | null;
  llmRetry: LLMRetryState | null;
}

interface ActiveStreamingMessage extends StreamingAssistantMessage {
  sessionId: string;
}

interface MessageDeltaEvent {
  session_id: string;
  message_id: string;
  delta: string;
}

interface ScopedEvent {
  session_id: string;
}

interface LLMRetryEvent extends ScopedEvent {
  category: string;
  attempt: number;
  max_retries: number | null;
  delay_seconds: number;
}

export function useColonyEvents(
  colonyId: string | undefined,
  queenSessionId?: string,
  persistedMessageIds: readonly string[] = [],
) {
  return useScopedEvents("colonies", colonyId, queenSessionId, persistedMessageIds);
}

export function useSessionEvents(
  sessionId: string | undefined,
  persistedMessageIds: readonly string[] = [],
) {
  return useScopedEvents("sessions", sessionId, sessionId, persistedMessageIds);
}

function useScopedEvents(
  scope: "colonies" | "sessions",
  resourceId: string | undefined,
  queenSessionId?: string,
  persistedMessageIds: readonly string[] = [],
) {
  const queryClient = useQueryClient();
  const [streamingMessage, setStreamingMessage] = useState<ActiveStreamingMessage | null>(null);
  const [activeRetry, setActiveRetry] = useState<(LLMRetryState & { sessionId: string }) | null>(null);

  useEffect(() => {
    if (!resourceId) return undefined;
    const source = new EventSource(`/api/${scope}/${resourceId}/events?after=0`);

    const listeners = EVENT_TYPES.map((type) => {
      const listener = (event: Event) => {
        if (scope === "colonies") {
          void queryClient.invalidateQueries({ queryKey: ["colony", resourceId] });
        } else {
          void queryClient.invalidateQueries({ queryKey: ["session", resourceId] });
        }
        if (queenSessionId) {
          void queryClient.invalidateQueries({ queryKey: ["messages", queenSessionId] });
        }
        if (type === "llm.retrying") {
          const data = parseRetryEvent(event);
          if (data && data.session_id === queenSessionId) {
            setActiveRetry({
              sessionId: data.session_id,
              category: data.category,
              attempt: data.attempt,
              maxRetries: data.max_retries,
              delaySeconds: data.delay_seconds,
            });
          }
        } else if ([
          "message.completed",
          "session.idle",
          "session.parked",
          "session.failed",
          "llm.retry_exhausted",
        ].includes(type)) {
          const data = parseScopedEvent(event);
          if (data?.session_id === queenSessionId) setActiveRetry(null);
        }
      };
      source.addEventListener(type, listener);
      return [type, listener] as const;
    });

    const deltaListener = (event: Event) => {
      const data = parseDeltaEvent(event);
      if (!data || data.session_id !== queenSessionId) return;
      setActiveRetry(null);
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
  }, [scope, resourceId, queenSessionId, queryClient]);

  const visibleStreamingMessage = !streamingMessage ||
    streamingMessage.sessionId !== queenSessionId ||
    persistedMessageIds.includes(streamingMessage.id)
    ? null
    : streamingMessage;
  const visibleRetry = activeRetry?.sessionId === queenSessionId ? activeRetry : null;
  return {
    streamingMessage: visibleStreamingMessage
      ? { id: visibleStreamingMessage.id, content: visibleStreamingMessage.content }
      : null,
    llmRetry: visibleRetry
      ? {
          category: visibleRetry.category,
          attempt: visibleRetry.attempt,
          maxRetries: visibleRetry.maxRetries,
          delaySeconds: visibleRetry.delaySeconds,
        }
      : null,
  } satisfies AgentEventState;
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

function parseScopedEvent(event: Event): ScopedEvent | null {
  const data = parseEventData(event);
  return data && typeof data.session_id === "string"
    ? { session_id: data.session_id }
    : null;
}

function parseRetryEvent(event: Event): LLMRetryEvent | null {
  const data = parseEventData(event);
  if (
    !data ||
    typeof data.session_id !== "string" ||
    typeof data.category !== "string" ||
    typeof data.attempt !== "number" ||
    !(typeof data.max_retries === "number" || data.max_retries === null) ||
    typeof data.delay_seconds !== "number"
  ) return null;
  return {
    session_id: data.session_id,
    category: data.category,
    attempt: data.attempt,
    max_retries: data.max_retries,
    delay_seconds: data.delay_seconds,
  };
}

function parseEventData(event: Event): Record<string, unknown> | null {
  if (!(event instanceof MessageEvent) || typeof event.data !== "string") return null;
  try {
    const data: unknown = JSON.parse(event.data);
    return isRecord(data) ? data : null;
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
