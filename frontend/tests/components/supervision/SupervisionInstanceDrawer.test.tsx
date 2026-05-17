import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";
import { SupervisionInstanceDrawer } from "@/components/supervision/SupervisionInstanceDrawer";
import { supervisionApi, type InstanceDetail } from "@/lib/supervisionApi";

vi.mock("@/lib/supervisionApi", async () => {
  const real = await vi.importActual<typeof import("@/lib/supervisionApi")>(
    "@/lib/supervisionApi",
  );
  return { ...real, supervisionApi: { ...real.supervisionApi, getInstance: vi.fn() } };
});

const detail: InstanceDetail = {
  id: "11111111-1111-4111-8111-111111111111",
  session_id: "22222222-2222-4222-8222-222222222222",
  agent_id: "claude-code-r1",
  mission: "refactor auth",
  status: "busy",
  last_activity_at: "2026-05-17T10:00:00Z",
  created_at: "2026-05-17T09:00:00Z",
  destroyed_at: null,
  error_message: null,
  last_container_name: "agent-abc",
  container_status: "running",
  labels: { role: "developer" },
  mom_counts: { pending: 0, claimed: 3, failed: 0 },
  recent_messages: [
    { msg_id: "m1", direction: "in", kind: "instruction", payload: "go", created_at: "2026-05-17T09:50:00Z" },
    { msg_id: "m2", direction: "out", kind: "event", payload: "ack", created_at: "2026-05-17T09:55:00Z" },
  ],
};

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>
    </QueryClientProvider>
  );
}

describe("SupervisionInstanceDrawer", () => {
  beforeEach(() => {
    vi.mocked(supervisionApi.getInstance).mockReset();
    vi.mocked(supervisionApi.getInstance).mockResolvedValue(detail);
  });

  it("rend le détail quand instanceId est fourni", async () => {
    render(wrap(<SupervisionInstanceDrawer instanceId={detail.id} onClose={() => {}} />));
    expect(await screen.findByText(/refactor auth/i)).toBeInTheDocument();
    expect(screen.getByText("agent-abc")).toBeInTheDocument();
    expect(screen.getByText(/running/i)).toBeInTheDocument();
  });

  it("ne fetch pas si instanceId est null", () => {
    render(wrap(<SupervisionInstanceDrawer instanceId={null} onClose={() => {}} />));
    expect(supervisionApi.getInstance).not.toHaveBeenCalled();
  });

  it("affiche les labels JSON", async () => {
    render(wrap(<SupervisionInstanceDrawer instanceId={detail.id} onClose={() => {}} />));
    await screen.findByText(/refactor auth/i);
    expect(screen.getByText(/"role"/)).toBeInTheDocument();
  });

  it("affiche les recent_messages", async () => {
    render(wrap(<SupervisionInstanceDrawer instanceId={detail.id} onClose={() => {}} />));
    await screen.findByText(/refactor auth/i);
    expect(screen.getByText("instruction")).toBeInTheDocument();
    expect(screen.getByText("event")).toBeInTheDocument();
  });
});
