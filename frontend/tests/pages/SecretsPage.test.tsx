import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SecretsPage } from "@/pages/SecretsPage";
import { secretsApi } from "@/lib/secretsApi";
import "@/lib/i18n";

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

const MOCK_SECRET = {
  id: "00000000-0000-0000-0000-000000000001",
  key: "${env://ANTHROPIC_API_KEY}",
  type: "env" as const,
  name: "ANTHROPIC_API_KEY",
  has_value: true,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SecretsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SecretsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the list of secrets", async () => {
    vi.mocked(secretsApi.list).mockResolvedValueOnce([MOCK_SECRET]);

    renderPage();

    expect(await screen.findByText("ANTHROPIC_API_KEY")).toBeInTheDocument();
  });

  it("opens vault form when 'Ajouter un secret' is clicked", async () => {
    vi.mocked(secretsApi.list).mockResolvedValueOnce([]);

    renderPage();

    await waitFor(() =>
      expect(screen.queryByText(/Chargement/)).not.toBeInTheDocument(),
    );

    await userEvent.click(
      screen.getByRole("button", { name: /Ajouter un secret/ }),
    );
    expect(screen.getByText(/Nouveau secret \(coffre/)).toBeInTheDocument();
  });

  it("opens env form when 'Ajouter une variable' is clicked", async () => {
    vi.mocked(secretsApi.list).mockResolvedValueOnce([]);

    renderPage();

    await waitFor(() =>
      expect(screen.queryByText(/Chargement/)).not.toBeInTheDocument(),
    );

    await userEvent.click(
      screen.getByRole("button", { name: /Ajouter une variable/ }),
    );
    expect(screen.getByText(/Nouvelle variable/)).toBeInTheDocument();
  });
});
