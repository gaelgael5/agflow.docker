import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import React from "react";

import i18n from "@/lib/i18n";
import { AuthTab } from "../AuthTab";
import { authConfigApi, type AuthConfig } from "@/lib/authConfigApi";
import { api } from "@/lib/api";

vi.mock("@/lib/authConfigApi");
vi.mock("@/lib/api");

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={qc}>{node}</QueryClientProvider>
    </I18nextProvider>,
  );
}

const baseCfg: AuthConfig = {
  mode: "local",
  keycloak_url: "",
  keycloak_realm: "",
  keycloak_client_id: "",
  has_secret: false,
  vault_name: "default",
  updated_at: "2026-05-19T12:00:00Z",
  updated_by_user_id: null,
};

describe("AuthTab", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    (api.get as any).mockResolvedValue({
      data: [{ id: "v1", name: "default", url: "http://h", is_default: true }],
    });
  });

  it("renders form with local mode by default", async () => {
    (authConfigApi.getConfig as any).mockResolvedValue(baseCfg);
    wrap(<AuthTab />);
    await waitFor(() => screen.getByRole("radio", { name: /local/i }));
    const radioLocal = screen.getByRole("radio", { name: /local/i }) as HTMLInputElement;
    expect(radioLocal.checked).toBe(true);
  });

  it("disables Test button in local mode", async () => {
    (authConfigApi.getConfig as any).mockResolvedValue(baseCfg);
    wrap(<AuthTab />);
    await waitFor(() => screen.getByRole("button", { name: /tester/i }));
    const testBtn = screen.getByRole("button", { name: /tester/i });
    expect(testBtn).toBeDisabled();
  });

  it("enables Test button after switching to keycloak", async () => {
    const user = userEvent.setup();
    (authConfigApi.getConfig as any).mockResolvedValue(baseCfg);
    wrap(<AuthTab />);
    await waitFor(() => screen.getByRole("radio", { name: /keycloak/i }));
    await user.click(screen.getByRole("radio", { name: /keycloak/i }));
    await waitFor(() => {
      const testBtn = screen.getByRole("button", { name: /tester/i });
      expect(testBtn).not.toBeDisabled();
    });
  });

  it("calls update with the form values when Save clicked", async () => {
    const user = userEvent.setup();
    (authConfigApi.getConfig as any).mockResolvedValue(baseCfg);
    (authConfigApi.updateConfig as any).mockResolvedValue(baseCfg);
    wrap(<AuthTab />);
    await waitFor(() => screen.getByRole("radio", { name: /keycloak/i }));
    await user.click(screen.getByRole("radio", { name: /keycloak/i }));
    await waitFor(() => {
      const fieldset = screen.getByRole("group");
      expect(fieldset).not.toBeDisabled();
    });
    await user.clear(screen.getByLabelText(/URL Keycloak/i));
    await user.type(screen.getByLabelText(/URL Keycloak/i), "https://kc.example.com");
    await user.click(screen.getByRole("button", { name: /enregistrer/i }));
    await waitFor(() =>
      expect(authConfigApi.updateConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          mode: "keycloak",
          keycloak_url: "https://kc.example.com",
        }),
      ),
    );
  });

  it("shows test result with check marks on success", async () => {
    const user = userEvent.setup();
    (authConfigApi.getConfig as any).mockResolvedValue(baseCfg);
    (authConfigApi.testConnection as any).mockResolvedValue({
      ok: true,
      step: "done",
      detail: "OK",
      discovery_ok: true,
      token_ok: true,
    });
    wrap(<AuthTab />);
    await waitFor(() => screen.getByRole("radio", { name: /keycloak/i }));
    await user.click(screen.getByRole("radio", { name: /keycloak/i }));
    await waitFor(() => {
      const testBtn = screen.getByRole("button", { name: /tester/i });
      expect(testBtn).not.toBeDisabled();
    });
    await user.click(screen.getByRole("button", { name: /tester/i }));
    await waitFor(() => screen.getByText(/connexion valid/i));
  });
});
