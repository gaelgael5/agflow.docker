import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn() },
}));

import { api } from "@/lib/api";
import {
  supervisionApi,
  SupervisionOverviewSchema,
  SupervisedInstanceSchema,
} from "@/lib/supervisionApi";

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

describe("supervisionApi schemas", () => {
  it("parse une réponse overview valide", () => {
    const raw = {
      sessions: { active: 3, closed: 2, expired: 0 },
      agents: { idle: 5, busy: 2, error: 0, destroyed_total: 8 },
      containers_running: 12,
      mom: { pending: 0, claimed: 3, failed: 1 },
    };
    const parsed = SupervisionOverviewSchema.parse(raw);
    expect(parsed.containers_running).toBe(12);
    expect(parsed.mom.failed).toBe(1);
  });

  it("accepte containers_running null", () => {
    const raw = {
      sessions: { active: 0, closed: 0, expired: 0 },
      agents: { idle: 0, busy: 0, error: 0, destroyed_total: 0 },
      containers_running: null,
      mom: { pending: 0, claimed: 0, failed: 0 },
    };
    const parsed = SupervisionOverviewSchema.parse(raw);
    expect(parsed.containers_running).toBeNull();
  });

  it("parse une SupervisedInstance avec destroyed_at null", () => {
    const raw = {
      id: "11111111-1111-4111-8111-111111111111",
      session_id: "22222222-2222-4222-8222-222222222222",
      agent_id: "claude-code-r1",
      mission: "refactor",
      status: "busy",
      last_activity_at: "2026-05-17T10:00:00Z",
      created_at: "2026-05-17T09:00:00Z",
      destroyed_at: null,
      error_message: null,
      last_container_name: "agent-abc",
    };
    const parsed = SupervisedInstanceSchema.parse(raw);
    expect(parsed.status).toBe("busy");
    expect(parsed.destroyed_at).toBeNull();
  });
});

describe("supervisionApi", () => {
  it("construit les bons query params", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: [] });

    await supervisionApi.listInstances({ status: "busy", limit: 50 });

    expect(api.get).toHaveBeenCalledWith(
      "/admin/supervision/instances?status=busy&limit=50",
    );
  });

  it("getOverview appelle l'endpoint et parse la réponse via Zod", async () => {
    const overview = {
      sessions: { active: 1, closed: 0, expired: 0 },
      agents: { idle: 2, busy: 0, error: 0, destroyed_total: 0 },
      containers_running: null,
      mom: { pending: 0, claimed: 0, failed: 0 },
    };
    vi.mocked(api.get).mockResolvedValueOnce({ data: overview });
    const result = await supervisionApi.getOverview();
    expect(api.get).toHaveBeenCalledWith("/admin/supervision/overview");
    expect(result).toEqual(overview);
  });

  it("getInstance interpole l'id dans l'URL", async () => {
    const id = "11111111-1111-4111-8111-111111111111";
    const detail = {
      id,
      session_id: "22222222-2222-4222-8222-222222222222",
      agent_id: "claude-r1",
      mission: null,
      status: "idle",
      last_activity_at: "2026-05-17T10:00:00Z",
      created_at: "2026-05-17T09:00:00Z",
      destroyed_at: null,
      error_message: null,
      last_container_name: null,
      container_status: null,
      labels: {},
      mom_counts: { pending: 0, claimed: 0, failed: 0 },
      recent_messages: [],
    };
    vi.mocked(api.get).mockResolvedValueOnce({ data: detail });
    const result = await supervisionApi.getInstance(id);
    expect(api.get).toHaveBeenCalledWith(
      `/admin/supervision/instances/${id}`,
    );
    expect(result.id).toBe(id);
  });

  it("listInstances sans params ne met pas de query string", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: [] });
    await supervisionApi.listInstances();
    expect(api.get).toHaveBeenCalledWith("/admin/supervision/instances");
  });
});
