import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionAgentTimelinePage } from "@/pages/SessionAgentTimelinePage";
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

function renderAt(sessionId: string, instanceId: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/sessions/${sessionId}/agents/${instanceId}`]}>
        <Routes>
          <Route
            path="/sessions/:id/agents/:instanceId"
            element={<SessionAgentTimelinePage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SessionAgentTimelinePage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("affiche la timeline des messages", async () => {
    vi.mocked(sessionsApi.get).mockResolvedValueOnce({
      id: "s1",
      name: null,
      status: "active",
      project_id: null,
      api_key_id: "k1",
      created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      closed_at: null,
    });
    vi.mocked(sessionsApi.listAgents).mockResolvedValueOnce([
      {
        id: "a1",
        session_id: "s1",
        agent_id: "claude-code",
        labels: {},
        mission: "m",
        status: "busy",
        created_at: new Date().toISOString(),
      },
    ]);
    vi.mocked(sessionsApi.listMessages).mockResolvedValueOnce([
      {
        msg_id: "m1",
        parent_msg_id: null,
        direction: "in",
        kind: "llm_call",
        payload: { prompt: "Hello" },
        source: null,
        created_at: new Date().toISOString(),
        route: null,
      },
      {
        msg_id: "m2",
        parent_msg_id: "m1",
        direction: "out",
        kind: "tool_call",
        payload: { tool: "read_file" },
        source: null,
        created_at: new Date().toISOString(),
        route: null,
      },
    ]);

    renderAt("s1", "a1");
    await waitFor(() =>
      expect(screen.getByText("llm_call")).toBeInTheDocument(),
    );
    expect(screen.getByText("tool_call")).toBeInTheDocument();
  });

  it("affiche état vide", async () => {
    vi.mocked(sessionsApi.get).mockResolvedValueOnce({
      id: "s1",
      name: null,
      status: "active",
      project_id: null,
      api_key_id: "k1",
      created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      closed_at: null,
    });
    vi.mocked(sessionsApi.listAgents).mockResolvedValueOnce([
      {
        id: "a1",
        session_id: "s1",
        agent_id: "claude-code",
        labels: {},
        mission: "m",
        status: "busy",
        created_at: new Date().toISOString(),
      },
    ]);
    vi.mocked(sessionsApi.listMessages).mockResolvedValueOnce([]);

    renderAt("s1", "a1");
    await waitFor(() =>
      expect(screen.getByText(/aucun message/i)).toBeInTheDocument(),
    );
  });
});
