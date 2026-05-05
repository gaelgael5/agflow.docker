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
        name: "ANTHROPIC_API_KEY",
        is_placeholder: false,
        description: null,
        tags: [],
      },
    ]);

    const { result } = renderHook(() => useSecrets(), { wrapper });

    await waitFor(() => {
      expect(result.current.secrets).toHaveLength(1);
    });
    expect(result.current.secrets?.[0]?.name).toBe("ANTHROPIC_API_KEY");
  });

  it("creates a secret via mutation", async () => {
    vi.mocked(secretsApi.list).mockResolvedValue([]);
    vi.mocked(secretsApi.create).mockResolvedValueOnce({
      name: "OPENAI_API_KEY",
      is_placeholder: false,
      description: null,
      tags: [],
    });

    const { result } = renderHook(() => useSecrets(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.createMutation.mutateAsync({
      name: "OPENAI_API_KEY",
      value: "sk-openai",
    });

    expect(secretsApi.create).toHaveBeenCalledWith({
      name: "OPENAI_API_KEY",
      value: "sk-openai",
    });
  });
});
