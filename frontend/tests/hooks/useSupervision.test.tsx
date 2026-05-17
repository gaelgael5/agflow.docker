import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import {
  useOverview,
  useInstances,
  useInstanceDetail,
} from "@/hooks/useSupervision";
import { supervisionApi } from "@/lib/supervisionApi";

vi.mock("@/lib/supervisionApi", () => ({
  supervisionApi: {
    getOverview: vi.fn(),
    listInstances: vi.fn(),
    getInstance: vi.fn(),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useSupervision", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("useOverview appelle getOverview", async () => {
    vi.mocked(supervisionApi.getOverview).mockResolvedValue({
      sessions: { active: 1, closed: 0, expired: 0 },
      agents: { idle: 0, busy: 0, error: 0, destroyed_total: 0 },
      containers_running: null,
      mom: { pending: 0, claimed: 0, failed: 0 },
    });
    const { result } = renderHook(() => useOverview(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(supervisionApi.getOverview).toHaveBeenCalled();
  });

  it("useInstanceDetail est désactivé si id est null", () => {
    const { result } = renderHook(() => useInstanceDetail(null), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
    expect(supervisionApi.getInstance).not.toHaveBeenCalled();
  });

  it("useInstances avec includeDestroyed=true merge alive et destroyed", async () => {
    vi.mocked(supervisionApi.listInstances).mockImplementation(
      async (params) => {
        if (params?.status === "destroyed")
          return [
            {
              id: "d1111111-1111-4111-8111-111111111111",
              session_id: "d2222222-2222-4222-8222-222222222222",
              agent_id: "x",
              mission: null,
              status: "destroyed",
              last_activity_at: "2026-05-17T00:00:00Z",
              created_at: "2026-05-17T00:00:00Z",
              destroyed_at: "2026-05-17T00:00:00Z",
              error_message: null,
              last_container_name: null,
            },
          ];
        return [
          {
            id: "a1111111-1111-4111-8111-111111111111",
            session_id: "a2222222-2222-4222-8222-222222222222",
            agent_id: "y",
            mission: null,
            status: "idle",
            last_activity_at: "2026-05-17T01:00:00Z",
            created_at: "2026-05-17T01:00:00Z",
            destroyed_at: null,
            error_message: null,
            last_container_name: null,
          },
        ];
      },
    );
    const { result } = renderHook(
      () => useInstances({ status: undefined, includeDestroyed: true }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const ids = (result.current.data ?? []).map((i) => i.id);
    expect(ids).toContain("a1111111-1111-4111-8111-111111111111");
    expect(ids).toContain("d1111111-1111-4111-8111-111111111111");
  });
});
