import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";
import { SupervisionPage } from "@/pages/SupervisionPage";
import { supervisionApi } from "@/lib/supervisionApi";

vi.mock("@/lib/supervisionApi", async () => {
  const real = await vi.importActual<typeof import("@/lib/supervisionApi")>(
    "@/lib/supervisionApi",
  );
  return {
    ...real,
    supervisionApi: {
      ...real.supervisionApi,
      getOverview: vi.fn().mockResolvedValue({
        sessions: { active: 1, closed: 0, expired: 0 },
        agents: { idle: 0, busy: 1, error: 0, destroyed_total: 0 },
        containers_running: 2,
        mom: { pending: 0, claimed: 0, failed: 0 },
      }),
      listInstances: vi.fn().mockResolvedValue([
        {
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          session_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
          agent_id: "claude-code-r1",
          mission: "refactor auth",
          status: "busy",
          last_activity_at: "2026-05-17T10:00:00Z",
          created_at: "2026-05-17T09:00:00Z",
          destroyed_at: null,
          error_message: null,
          last_container_name: "agent-abc",
        },
      ]),
      getInstance: vi.fn().mockResolvedValue({
        id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        session_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        agent_id: "claude-code-r1",
        mission: "refactor auth",
        status: "busy",
        last_activity_at: "2026-05-17T10:00:00Z",
        created_at: "2026-05-17T09:00:00Z",
        destroyed_at: null,
        error_message: null,
        last_container_name: "agent-abc",
        container_status: "running",
        labels: {},
        mom_counts: { pending: 0, claimed: 0, failed: 0 },
        recent_messages: [],
      }),
    },
  };
});

function renderWithUrl(initialUrl: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <QueryClientProvider client={client}>
        <I18nextProvider i18n={i18n}>
          <SupervisionPage />
        </I18nextProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("SupervisionPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("ouvre le drawer quand ?instance=<id> est dans l'URL", async () => {
    renderWithUrl("/supervision?instance=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
    await screen.findAllByText(/refactor auth/i);
    expect(supervisionApi.getInstance).toHaveBeenCalledWith(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
  });

  it("clic sur une ligne ajoute ?instance=<id> et fetch le détail", async () => {
    renderWithUrl("/supervision");
    const cell = await screen.findByText(/refactor auth/i);
    fireEvent.click(cell.closest("tr")!);
    expect(supervisionApi.getInstance).toHaveBeenCalledWith(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
  });
});
