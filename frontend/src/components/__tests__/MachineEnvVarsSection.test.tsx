import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MachineEnvVarsSection } from "@/components/MachineEnvVarsSection";
import * as infraEnvVarsApi from "@/lib/infraEnvVarsApi";

vi.mock("@/lib/infraEnvVarsApi");
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/components/StatusIndicator", () => ({
  StatusIndicator: ({ status }: { status: string }) => <span data-testid={`status-${status}`} />,
}));
vi.mock("@/hooks/useHarpocrateVaults", () => ({
  useHarpocrateVaults: () => ({ vaults: [], defaultVault: undefined, isLoading: false }),
}));

const MACHINE_ID = "m-1";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("MachineEnvVarsSection", () => {
  beforeEach(() => {
    vi.mocked(infraEnvVarsApi.machineEnvVarsApi.list).mockResolvedValue([]);
  });

  it("affiche le message vide si aucune variable dans le contrat", async () => {
    render(<MachineEnvVarsSection machineId={MACHINE_ID} />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("infra.machine_env_vars_empty")).toBeInTheDocument();
    });
  });

  it("affiche les variables avec leur valeur courante", async () => {
    vi.mocked(infraEnvVarsApi.machineEnvVarsApi.list).mockResolvedValue([
      {
        id: "mv-1",
        machine_id: MACHINE_ID,
        named_type_env_var_id: "ev-1",
        name: "HOST",
        description: "The host",
        value: "example.com",
        is_secret: false,
        created_at: "",
        updated_at: "",
      },
    ]);
    render(<MachineEnvVarsSection machineId={MACHINE_ID} />, { wrapper });
    await waitFor(() => {
      expect(screen.getByDisplayValue("example.com")).toBeInTheDocument();
    });
  });

  it("appelle upsert au clic Enregistrer", async () => {
    vi.mocked(infraEnvVarsApi.machineEnvVarsApi.list).mockResolvedValue([
      {
        id: "mv-1",
        machine_id: MACHINE_ID,
        named_type_env_var_id: "ev-1",
        name: "HOST",
        description: "",
        value: "",
        is_secret: false,
        created_at: "",
        updated_at: "",
      },
    ]);
    vi.mocked(infraEnvVarsApi.machineEnvVarsApi.upsert).mockResolvedValue([]);
    render(<MachineEnvVarsSection machineId={MACHINE_ID} />, { wrapper });
    await waitFor(() => screen.getByText("infra.machine_env_vars_save_button"));
    const input = screen.getByPlaceholderText("infra.machine_env_var_value_placeholder");
    await userEvent.type(input, "new-value");
    await userEvent.click(screen.getByText("infra.machine_env_vars_save_button"));
    await waitFor(() => {
      expect(infraEnvVarsApi.machineEnvVarsApi.upsert).toHaveBeenCalledWith(
        MACHINE_ID,
        expect.objectContaining({ values: expect.objectContaining({ "ev-1": "new-value" }) }),
      );
    });
  });
});
