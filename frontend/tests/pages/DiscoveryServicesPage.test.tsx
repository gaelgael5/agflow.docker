import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DiscoveryServicesPage } from "@/pages/DiscoveryServicesPage";
import { discoveryApi } from "@/lib/catalogsApi";
import "@/lib/i18n";

vi.mock("@/lib/catalogsApi", () => ({
  discoveryApi: {
    list: vi.fn(),
    create: vi.fn(),
    remove: vi.fn(),
    test: vi.fn(),
    searchMcp: vi.fn(),
    searchSkills: vi.fn(),
  },
  mcpCatalogApi: { list: vi.fn(), install: vi.fn(), updateParameters: vi.fn(), remove: vi.fn() },
  skillsCatalogApi: { list: vi.fn(), install: vi.fn(), remove: vi.fn() },
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DiscoveryServicesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DiscoveryServicesPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows empty state", async () => {
    vi.mocked(discoveryApi.list).mockResolvedValueOnce([]);
    renderPage();
    expect(await screen.findByText(/Aucun registre/)).toBeInTheDocument();
  });

  it("lists services with API key variable", async () => {
    vi.mocked(discoveryApi.list).mockResolvedValueOnce([
      {
        id: "yoops",
        name: "yoops.org",
        base_url: "https://mcp.yoops.org/api/v1",
        api_key_var: "YOOPS_API_KEY",
        description: "",
        enabled: true,
        created_at: "2026-04-11",
        updated_at: "2026-04-11",
      },
    ]);

    renderPage();

    expect(await screen.findByText("yoops.org")).toBeInTheDocument();
    expect(screen.getByText("YOOPS_API_KEY")).toBeInTheDocument();
  });
});
