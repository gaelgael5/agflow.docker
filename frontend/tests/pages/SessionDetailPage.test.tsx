import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionDetailPage } from "@/pages/SessionDetailPage";
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

function renderAt(sessionId: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/sessions/${sessionId}`]}>
        <Routes>
          <Route path="/sessions/:id" element={<SessionDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SessionDetailPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("affiche les agents rattachés à la session", async () => {
    vi.mocked(sessionsApi.get).mockResolvedValueOnce({
      id: "11111111-2222-3333-4444-555555555555",
      name: "My session",
      status: "active",
      project_id: null,
      api_key_id: "k1",
      created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 60 * 60_000).toISOString(),
      closed_at: null,
    });
    vi.mocked(sessionsApi.listAgents).mockResolvedValueOnce([
      {
        id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        session_id: "11111111-2222-3333-4444-555555555555",
        agent_id: "claude-code",
        labels: {},
        mission: "refactor auth",
        status: "busy",
        created_at: new Date().toISOString(),
      },
    ]);

    renderAt("11111111-2222-3333-4444-555555555555");
    await waitFor(() =>
      expect(screen.getByText("claude-code")).toBeInTheDocument(),
    );
    expect(screen.getByText(/refactor auth/)).toBeInTheDocument();
  });

  it("affiche état vide si aucun agent", async () => {
    vi.mocked(sessionsApi.get).mockResolvedValueOnce({
      id: "11111111-2222-3333-4444-555555555555",
      name: null,
      status: "active",
      project_id: null,
      api_key_id: "k1",
      created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      closed_at: null,
    });
    vi.mocked(sessionsApi.listAgents).mockResolvedValueOnce([]);

    renderAt("11111111-2222-3333-4444-555555555555");
    await waitFor(() =>
      expect(screen.getByText(/aucun agent/i)).toBeInTheDocument(),
    );
  });
});
