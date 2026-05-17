import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useSupervisionStream } from "@/hooks/useSupervisionStream";
import type { ReactNode } from "react";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  readyState = 0;
  url: string;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
    queueMicrotask(() => {
      this.readyState = 1;
      this.onopen?.(new Event("open"));
    });
  }

  send() {}
  close() {
    this.closed = true;
    this.readyState = 3;
    this.onclose?.(new CloseEvent("close"));
  }

  emit(data: unknown) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
  }
}

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useSupervisionStream", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    FakeWebSocket.instances = [];
    localStorage.setItem("agflow_token", "test-token");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("ouvre WS avec token en query param", async () => {
    const client = new QueryClient();
    renderHook(() => useSupervisionStream(), { wrapper: wrapper(client) });
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    expect(FakeWebSocket.instances[0]!.url).toContain("token=test-token");
    expect(FakeWebSocket.instances[0]!.url).toContain("/api/admin/supervision/stream");
  });

  it("invalide overview+instances+instance(id) sur event instance.status_changed", async () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    renderHook(() => useSupervisionStream(), { wrapper: wrapper(client) });
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => {
      FakeWebSocket.instances[0]!.emit({
        type: "instance.status_changed",
        id: "abc-1",
      });
    });
    const calls = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(calls.some((k) => k?.includes("overview"))).toBe(true);
    expect(calls.some((k) => k?.includes("instances"))).toBe(true);
    expect(calls.some((k) => k?.includes("abc-1"))).toBe(true);
  });

  it('statut passe à "open" puis "closed" sur close', async () => {
    const client = new QueryClient();
    const { result } = renderHook(() => useSupervisionStream(), {
      wrapper: wrapper(client),
    });
    await waitFor(() => expect(result.current).toBe("open"));
    act(() => {
      FakeWebSocket.instances[0]!.close();
    });
    expect(result.current).toBe("closed");
  });

  it("reconnect après close avec backoff (au moins 1 reconnexion)", async () => {
    vi.useFakeTimers();
    const client = new QueryClient();
    renderHook(() => useSupervisionStream(), { wrapper: wrapper(client) });
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBeGreaterThanOrEqual(1));
    act(() => {
      FakeWebSocket.instances[0]!.close();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500); // > backoff initial 1s
    });
    expect(FakeWebSocket.instances.length).toBeGreaterThanOrEqual(2);
    vi.useRealTimers();
  });
});
