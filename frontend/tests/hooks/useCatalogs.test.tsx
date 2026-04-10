import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useDiscoveryServices } from "@/hooks/useCatalogs";
import { discoveryApi } from "@/lib/catalogsApi";

vi.mock("@/lib/catalogsApi", () => ({
  discoveryApi: {
    list: vi.fn(),
    create: vi.fn(),
    remove: vi.fn(),
    test: vi.fn(),
    searchMcp: vi.fn(),
    searchSkills: vi.fn(),
  },
  mcpCatalogApi: {
    list: vi.fn(),
    install: vi.fn(),
    updateParameters: vi.fn(),
    remove: vi.fn(),
  },
  skillsCatalogApi: {
    list: vi.fn(),
    install: vi.fn(),
    remove: vi.fn(),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useDiscoveryServices", () => {
  beforeEach(() => vi.clearAllMocks());

  it("loads services via api.list", async () => {
    vi.mocked(discoveryApi.list).mockResolvedValueOnce([
      {
        id: "yoops",
        name: "yoops.org",
        base_url: "https://mcp.yoops.org",
        api_key_var: "YOOPS_API_KEY",
        description: "",
        enabled: true,
        created_at: "2026-04-10",
        updated_at: "2026-04-10",
      },
    ]);

    const { result } = renderHook(() => useDiscoveryServices(), { wrapper });

    await waitFor(() => expect(result.current.services).toHaveLength(1));
    expect(result.current.services?.[0]?.id).toBe("yoops");
  });

  it("creates a service via mutation", async () => {
    vi.mocked(discoveryApi.list).mockResolvedValue([]);
    vi.mocked(discoveryApi.create).mockResolvedValueOnce({
      id: "new",
      name: "New",
      base_url: "https://x",
      api_key_var: null,
      description: "",
      enabled: true,
      created_at: "2026-04-10",
      updated_at: "2026-04-10",
    });

    const { result } = renderHook(() => useDiscoveryServices(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.createMutation.mutateAsync({
      id: "new",
      name: "New",
      base_url: "https://x",
    });

    expect(discoveryApi.create).toHaveBeenCalled();
  });
});
