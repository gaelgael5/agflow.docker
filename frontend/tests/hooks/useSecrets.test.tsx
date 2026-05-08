import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useSecrets } from "@/hooks/useSecrets";
import { secretsApi } from "@/lib/secretsApi";

vi.mock("@/lib/secretsApi", () => ({
  secretsApi: {
    list: vi.fn(),
    createVault: vi.fn(),
    createEnv: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    reveal: vi.fn(),
    resolveStatus: vi.fn(),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const MOCK_SECRET = {
  id: "00000000-0000-0000-0000-000000000001",
  key: "${env://ANTHROPIC_API_KEY}",
  type: "env" as const,
  name: "ANTHROPIC_API_KEY",
  has_value: true,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
};

describe("useSecrets", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads secrets via secretsApi.list", async () => {
    vi.mocked(secretsApi.list).mockResolvedValueOnce([MOCK_SECRET]);

    const { result } = renderHook(() => useSecrets(), { wrapper });

    await waitFor(() => {
      expect(result.current.secrets).toHaveLength(1);
    });
    expect(result.current.secrets?.[0]?.name).toBe("ANTHROPIC_API_KEY");
  });

  it("creates an env secret via mutation", async () => {
    vi.mocked(secretsApi.list).mockResolvedValue([]);
    vi.mocked(secretsApi.createEnv).mockResolvedValueOnce({
      ...MOCK_SECRET,
      name: "OPENAI_API_KEY",
      key: "${env://OPENAI_API_KEY}",
    });

    const { result } = renderHook(() => useSecrets(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.createEnvMutation.mutateAsync({
      name: "OPENAI_API_KEY",
      value: "sk-openai",
    });

    expect(secretsApi.createEnv).toHaveBeenCalledWith({
      name: "OPENAI_API_KEY",
      value: "sk-openai",
    });
  });
});
