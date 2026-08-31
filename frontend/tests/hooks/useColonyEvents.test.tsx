import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useColonyEvents } from "../../src/hooks/useColonyEvents";

class MockEventSource {
  static current: MockEventSource;

  private listeners = new Map<string, Set<(event: Event) => void>>();

  constructor(public readonly url: string) {
    MockEventSource.current = this;
  }

  addEventListener(type: string, listener: (event: Event) => void) {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: (event: Event) => void) {
    this.listeners.get(type)?.delete(listener);
  }

  close() {}

  emit(type: string, data: object) {
    const event = new MessageEvent(type, { data: JSON.stringify(data) });
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }
}

describe("useColonyEvents", () => {
  beforeEach(() => {
    vi.stubGlobal("EventSource", MockEventSource);
  });

  it("拼接原生消息增量，并在完整消息持久化后交还给查询结果", () => {
    const queryClient = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result, rerender, unmount } = renderHook(
      ({ persistedIds }) => useColonyEvents("colony-1", "session-1", persistedIds),
      { initialProps: { persistedIds: [] as string[] }, wrapper },
    );

    act(() => {
      MockEventSource.current.emit("message.delta", {
        session_id: "session-1",
        message_id: "message-1",
        delta: "原生",
      });
      MockEventSource.current.emit("message.delta", {
        session_id: "session-1",
        message_id: "message-1",
        delta: "流式",
      });
    });
    expect(result.current).toEqual({ id: "message-1", content: "原生流式" });

    rerender({ persistedIds: ["message-1"] });
    expect(result.current).toBeNull();
    unmount();
  });

  it("收到取消事件后移除工具调用产生的临时文本", () => {
    const queryClient = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result, unmount } = renderHook(
      () => useColonyEvents("colony-1", "session-1"),
      { wrapper },
    );

    act(() => {
      MockEventSource.current.emit("message.delta", {
        session_id: "session-1",
        message_id: "message-2",
        delta: "内部过程",
      });
      MockEventSource.current.emit("message.stream.cancelled", {
        session_id: "session-1",
        message_id: "message-2",
      });
    });
    expect(result.current).toBeNull();
    unmount();
  });
});
