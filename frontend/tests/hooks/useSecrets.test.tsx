import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useSecrets } from "@/hooks/useSecrets";
import { secretsApi } from "@/lib/secretsApi";

vi.mock("@/lib/secretsApi", () => ({
  secretsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    reveal: vi.fn(),
    test: vi.fn(),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useSecrets", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads secrets via secretsApi.list", async () => {
    vi.mocked(secretsApi.list).mockResolvedValueOnce([
      {
        id: "1",
        var_name: "ANTHROPIC_API_KEY",
        scope: "global",
        created_at: "2026-04-10",
        updated_at: "2026-04-10",
        used_by: [],
      },
    ]);

    const { result } = renderHook(() => useSecrets(), { wrapper });

    await waitFor(() => {
      expect(result.current.secrets).toHaveLength(1);
    });
    expect(result.current.secrets?.[0]?.var_name).toBe("ANTHROPIC_API_KEY");
  });

  it("creates a secret via mutation", async () => {
    vi.mocked(secretsApi.list).mockResolvedValue([]);
    vi.mocked(secretsApi.create).mockResolvedValueOnce({
      id: "2",
      var_name: "OPENAI_API_KEY",
      scope: "global",
      created_at: "2026-04-10",
      updated_at: "2026-04-10",
      used_by: [],
    });

    const { result } = renderHook(() => useSecrets(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.createMutation.mutateAsync({
      var_name: "OPENAI_API_KEY",
      value: "sk-openai",
    });

    expect(secretsApi.create).toHaveBeenCalledWith({
      var_name: "OPENAI_API_KEY",
      value: "sk-openai",
    });
  });
});
