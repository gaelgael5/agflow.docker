import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionsPage } from "@/pages/SessionsPage";
import { sessionsApi } from "@/lib/sessionsApi";
import "@/lib/i18n";

vi.mock("@/lib/sessionsApi", () => ({
  sessionsApi: {
    list: vi.fn(),
    get: vi.fn(),
    listAgents: vi.fn(),
    listMessages: vi.fn(),
  },
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SessionsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SessionsPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("affiche les sessions ad hoc et les groupes projet", async () => {
    vi.mocked(sessionsApi.list).mockResolvedValueOnce([
      {
        id: "11111111-2222-3333-4444-555555555555",
        name: "sess-1",
        status: "active",
        project_id: null,
        api_key_id: "k1",
        created_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 3600_000).toISOString(),
        closed_at: null,
        agent_count: 2,
      },
      {
        id: "66666666-7777-8888-9999-aaaaaaaaaaaa",
        name: "sess-2",
        status: "active",
        project_id: "frontend-refactor",
        api_key_id: "k1",
        created_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 3600_000).toISOString(),
        closed_at: null,
        agent_count: 1,
      },
    ]);

    renderPage();
    await waitFor(() =>
      expect(screen.getByText("sess-1")).toBeInTheDocument(),
    );
    expect(screen.getByText("sess-2")).toBeInTheDocument();
    expect(screen.getByText("frontend-refactor")).toBeInTheDocument();
  });

  it("affiche l'état vide quand aucune session", async () => {
    vi.mocked(sessionsApi.list).mockResolvedValueOnce([]);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/aucune session/i)).toBeInTheDocument(),
    );
  });
});
