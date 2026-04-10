import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useRoles } from "@/hooks/useRoles";
import { rolesApi } from "@/lib/rolesApi";

vi.mock("@/lib/rolesApi", () => ({
  rolesApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    generatePrompts: vi.fn(),
    createDocument: vi.fn(),
    updateDocument: vi.fn(),
    deleteDocument: vi.fn(),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useRoles", () => {
  beforeEach(() => vi.clearAllMocks());

  it("loads roles via rolesApi.list", async () => {
    vi.mocked(rolesApi.list).mockResolvedValueOnce([
      {
        id: "analyst",
        display_name: "Analyst",
        description: "",
        service_types: [],
        identity_md: "",
        prompt_orchestrator_md: "",
        runtime_config: {},
        created_at: "2026-04-10",
        updated_at: "2026-04-10",
      },
    ]);

    const { result } = renderHook(() => useRoles(), { wrapper });

    await waitFor(() => expect(result.current.roles).toHaveLength(1));
    expect(result.current.roles?.[0]?.id).toBe("analyst");
  });

  it("creates a role via mutation", async () => {
    vi.mocked(rolesApi.list).mockResolvedValue([]);
    vi.mocked(rolesApi.create).mockResolvedValueOnce({
      id: "new",
      display_name: "New",
      description: "",
      service_types: [],
      identity_md: "",
      prompt_orchestrator_md: "",
      runtime_config: {},
      created_at: "2026-04-10",
      updated_at: "2026-04-10",
    });

    const { result } = renderHook(() => useRoles(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.createMutation.mutateAsync({
      id: "new",
      display_name: "New",
    });

    expect(rolesApi.create).toHaveBeenCalled();
  });
});
