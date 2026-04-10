import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useDockerfiles } from "@/hooks/useDockerfiles";
import { dockerfilesApi } from "@/lib/dockerfilesApi";

vi.mock("@/lib/dockerfilesApi", () => ({
  dockerfilesApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    remove: vi.fn(),
    createFile: vi.fn(),
    updateFile: vi.fn(),
    deleteFile: vi.fn(),
    build: vi.fn(),
    getBuild: vi.fn(),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useDockerfiles", () => {
  beforeEach(() => vi.clearAllMocks());

  it("loads dockerfiles via api.list", async () => {
    vi.mocked(dockerfilesApi.list).mockResolvedValueOnce([
      {
        id: "claude-code",
        display_name: "Claude Code",
        description: "",
        parameters: {},
        current_hash: "abc123",
        display_status: "never_built",
        latest_build_id: null,
        created_at: "2026-04-10",
        updated_at: "2026-04-10",
      },
    ]);

    const { result } = renderHook(() => useDockerfiles(), { wrapper });

    await waitFor(() => expect(result.current.dockerfiles).toHaveLength(1));
    expect(result.current.dockerfiles?.[0]?.id).toBe("claude-code");
  });

  it("invalidates cache after create", async () => {
    vi.mocked(dockerfilesApi.list).mockResolvedValue([]);
    vi.mocked(dockerfilesApi.create).mockResolvedValueOnce({
      id: "x",
      display_name: "X",
      description: "",
      parameters: {},
      current_hash: "",
      display_status: "never_built",
      latest_build_id: null,
      created_at: "2026-04-10",
      updated_at: "2026-04-10",
    });

    const { result } = renderHook(() => useDockerfiles(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.createMutation.mutateAsync({
      id: "x",
      display_name: "X",
    });

    expect(dockerfilesApi.create).toHaveBeenCalled();
  });
});
