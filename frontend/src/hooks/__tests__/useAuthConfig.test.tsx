import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

import { useAuthConfig } from "../useAuthConfig";
import { authConfigApi, type AuthConfig } from "@/lib/authConfigApi";

vi.mock("@/lib/authConfigApi");

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const fakeConfig: AuthConfig = {
  mode: "local",
  keycloak_url: "",
  keycloak_realm: "",
  keycloak_client_id: "",
  has_secret: false,
  vault_name: "default",
  updated_at: "2026-05-19T12:00:00Z",
  updated_by_user_id: null,
};

describe("useAuthConfig", () => {
  beforeEach(() => vi.resetAllMocks());

  it("fetches the config", async () => {
    (authConfigApi.getConfig as any).mockResolvedValue(fakeConfig);
    const { result } = renderHook(() => useAuthConfig(), { wrapper });
    await waitFor(() => expect(result.current.data?.mode).toBe("local"));
  });

  it("calls update when mutate is invoked", async () => {
    (authConfigApi.getConfig as any).mockResolvedValue(fakeConfig);
    (authConfigApi.updateConfig as any).mockResolvedValue({ ...fakeConfig, mode: "keycloak" });
    const { result } = renderHook(() => useAuthConfig(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    result.current.update.mutate({ mode: "keycloak" });
    await waitFor(() =>
      expect(authConfigApi.updateConfig).toHaveBeenCalledWith({ mode: "keycloak" })
    );
  });

  it("calls test connection", async () => {
    (authConfigApi.getConfig as any).mockResolvedValue(fakeConfig);
    (authConfigApi.testConnection as any).mockResolvedValue({
      ok: true, step: "done", detail: "OK", discovery_ok: true, token_ok: true,
    });
    const { result } = renderHook(() => useAuthConfig(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    result.current.test.mutate({
      keycloak_url: "https://x.com", keycloak_realm: "r", keycloak_client_id: "c", keycloak_client_secret: "s",
    });
    await waitFor(() => expect(authConfigApi.testConnection).toHaveBeenCalled());
  });
});
