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
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    reveal: vi.fn(),
    test: vi.fn(),
  },
}));

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
    vi.mocked(secretsApi.list).mockResolvedValueOnce([
      {
        id: "1",
        var_name: "ANTHROPIC_API_KEY",
        scope: "global",
        created_at: "2026-04-10T12:00:00Z",
        updated_at: "2026-04-10T12:00:00Z",
        used_by: [],
      },
    ]);

    renderPage();

    expect(await screen.findByText("ANTHROPIC_API_KEY")).toBeInTheDocument();
  });

  it("opens the form when Add is clicked", async () => {
    vi.mocked(secretsApi.list).mockResolvedValueOnce([]);

    renderPage();

    await waitFor(() =>
      expect(screen.queryByText(/Chargement/)).not.toBeInTheDocument(),
    );

    await userEvent.click(
      screen.getByRole("button", { name: /Ajouter un secret/ }),
    );
    expect(screen.getByText(/Nouveau secret/)).toBeInTheDocument();
  });
});
