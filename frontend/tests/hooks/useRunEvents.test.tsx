import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRunEvents } from "../../src/hooks/useRunEvents";

class MockEventSource {
  static instance: MockEventSource;
  readonly listeners = new Map<string, EventListener[]>();
  readonly close = vi.fn();
  onerror: ((event: Event) => void) | null = null;
  onopen: ((event: Event) => void) | null = null;

  constructor(readonly url: string) {
    MockEventSource.instance = this;
  }

  addEventListener(type: string, listener: EventListener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  removeEventListener(type: string, listener: EventListener) {
    this.listeners.set(
      type,
      (this.listeners.get(type) ?? []).filter((item) => item !== listener),
    );
  }

  emit(type: string, sequence: number, payload: object) {
    const event = new MessageEvent(type, {
      data: JSON.stringify(payload),
      lastEventId: String(sequence),
    });
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }
}

beforeEach(() => {
  vi.stubGlobal("EventSource", MockEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useRunEvents", () => {
  it("collects named SSE events, refreshes the run, and closes at terminal state", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useRunEvents("run-1", true), { wrapper });
    const source = MockEventSource.instance;

    act(() => source.onopen?.(new Event("open")));
    expect(result.current.connected).toBe(true);

    act(() => source.emit("node.started", 1, { node_key: "research_apple" }));
    await waitFor(() => expect(result.current.events).toHaveLength(1));
    expect(result.current.events[0]?.nodeKey).toBe("research_apple");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["run", "run-1"] });

    act(() => source.emit("run.cancelled", 2, { status: "cancelled" }));
    expect(source.close).toHaveBeenCalled();
    expect(result.current.connected).toBe(false);
    expect(result.current.error).toBe("Run finished");
  });

  it("deduplicates replayed event sequences", async () => {
    const queryClient = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useRunEvents("run-2", true), { wrapper });
    const source = MockEventSource.instance;

    act(() => {
      source.emit("run.recovered", 3, { reset_nodes: 1 });
      source.emit("run.recovered", 3, { reset_nodes: 1 });
    });

    await waitFor(() => expect(result.current.events).toHaveLength(1));
  });
});
