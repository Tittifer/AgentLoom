import { useEffect } from "react";
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

export function useColonyEvents(colonyId: string | undefined, queenSessionId?: string) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!colonyId) return;
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

    return () => {
      listeners.forEach(([type, listener]) => source.removeEventListener(type, listener));
      source.close();
    };
  }, [colonyId, queenSessionId, queryClient]);
}
