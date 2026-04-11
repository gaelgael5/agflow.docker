import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AgentsPage } from "@/pages/AgentsPage";
import { agentsApi } from "@/lib/agentsApi";
import "@/lib/i18n";

vi.mock("@/lib/agentsApi", () => ({
  agentsApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    duplicate: vi.fn(),
    configPreview: vi.fn(),
  },
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AgentsPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows empty state when no agents", async () => {
    vi.mocked(agentsApi.list).mockResolvedValueOnce([]);
    renderPage();
    expect(await screen.findByText(/Aucun agent/)).toBeInTheDocument();
  });

  it("lists agents with slug + dockerfile + role", async () => {
    vi.mocked(agentsApi.list).mockResolvedValueOnce([
      {
        id: "11111111-1111-1111-1111-111111111111",
        slug: "my-agent",
        display_name: "My Agent",
        description: "",
        dockerfile_id: "claude-code",
        role_id: "senior-dev",
        env_vars: {},
        timeout_seconds: 3600,
        workspace_path: "/workspace",
        network_mode: "bridge",
        graceful_shutdown_secs: 30,
        force_kill_delay_secs: 10,
        created_at: "2026-04-11",
        updated_at: "2026-04-11",
        has_errors: false,
      },
    ]);

    renderPage();

    expect(await screen.findByText("my-agent")).toBeInTheDocument();
    expect(screen.getByText("My Agent")).toBeInTheDocument();
    expect(screen.getByText("claude-code")).toBeInTheDocument();
    expect(screen.getByText("senior-dev")).toBeInTheDocument();
  });
});
