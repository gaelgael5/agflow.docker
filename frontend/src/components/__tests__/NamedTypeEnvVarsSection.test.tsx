import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { NamedTypeEnvVarsSection } from "@/components/NamedTypeEnvVarsSection";
import * as infraEnvVarsApi from "@/lib/infraEnvVarsApi";

vi.mock("@/lib/infraEnvVarsApi");
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, string>) =>
      opts ? `${k}:${JSON.stringify(opts)}` : k,
  }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const NAMED_TYPE_ID = "nt-1";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.mocked(infraEnvVarsApi.namedTypeEnvVarsApi.list).mockResolvedValue([]);
});

describe("NamedTypeEnvVarsSection", () => {
  it("affiche le message vide si aucune variable", async () => {
    render(<NamedTypeEnvVarsSection namedTypeId={NAMED_TYPE_ID} />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("infra.env_vars_empty")).toBeInTheDocument();
    });
  });

  it("affiche les variables existantes", async () => {
    vi.mocked(infraEnvVarsApi.namedTypeEnvVarsApi.list).mockResolvedValue([
      {
        id: "ev-1",
        named_type_id: NAMED_TYPE_ID,
        name: "MY_VAR",
        description: "desc",
        position: 0,
        is_secret: false,
        created_at: "",
        updated_at: "",
      },
    ]);
    render(<NamedTypeEnvVarsSection namedTypeId={NAMED_TYPE_ID} />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("MY_VAR")).toBeInTheDocument();
    });
  });

  it("affiche la ligne d'ajout au clic sur Ajouter", async () => {
    render(<NamedTypeEnvVarsSection namedTypeId={NAMED_TYPE_ID} />, { wrapper });
    await waitFor(() => screen.getByText("infra.env_var_add_button"));
    await userEvent.click(screen.getByText("infra.env_var_add_button"));
    expect(screen.getByPlaceholderText("infra.env_var_name_placeholder")).toBeInTheDocument();
  });

  it("appelle create et ferme la ligne après soumission valide", async () => {
    vi.mocked(infraEnvVarsApi.namedTypeEnvVarsApi.create).mockResolvedValue({
      id: "ev-2",
      named_type_id: NAMED_TYPE_ID,
      name: "NEW_VAR",
      description: "",
      position: 0,
      is_secret: false,
      created_at: "",
      updated_at: "",
    });
    render(<NamedTypeEnvVarsSection namedTypeId={NAMED_TYPE_ID} />, { wrapper });
    await waitFor(() => screen.getByText("infra.env_var_add_button"));
    await userEvent.click(screen.getByText("infra.env_var_add_button"));
    await userEvent.type(screen.getByPlaceholderText("infra.env_var_name_placeholder"), "NEW_VAR");
    await userEvent.keyboard("{Enter}");
    await waitFor(() => {
      expect(infraEnvVarsApi.namedTypeEnvVarsApi.create).toHaveBeenCalledWith(
        NAMED_TYPE_ID,
        expect.objectContaining({ name: "NEW_VAR" }),
      );
    });
    // Vérifie que la ligne d'ajout est fermée
    await waitFor(() => {
      expect(screen.queryByPlaceholderText("infra.env_var_name_placeholder")).not.toBeInTheDocument();
    });
  });
});
