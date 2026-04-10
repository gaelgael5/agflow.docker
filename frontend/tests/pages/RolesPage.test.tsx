import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RolesPage } from "@/pages/RolesPage";
import { rolesApi } from "@/lib/rolesApi";
import "@/lib/i18n";

vi.mock("@/lib/rolesApi", () => ({
  rolesApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    generatePrompts: vi.fn(),
    createDocument: vi.fn(),
    updateDocument: vi.fn(),
    deleteDocument: vi.fn(),
  },
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RolesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RolesPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows empty state when no roles", async () => {
    vi.mocked(rolesApi.list).mockResolvedValueOnce([]);
    renderPage();
    expect(await screen.findByText(/Aucun rôle/)).toBeInTheDocument();
  });

  it("lists roles and shows add button", async () => {
    vi.mocked(rolesApi.list).mockResolvedValueOnce([
      {
        id: "analyst",
        display_name: "Analyst",
        description: "",
        service_types: [],
        identity_md: "",
        prompt_orchestrator_md: "",
        runtime_config: {},
        created_at: "2026-04-10",
        updated_at: "2026-04-10",
      },
    ]);

    renderPage();

    expect(await screen.findByText("Analyst")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Ajouter un rôle/ }),
    ).toBeInTheDocument();
  });
});
