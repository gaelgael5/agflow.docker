// frontend/src/lib/__tests__/restoreApi.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "../api";
import { restoreApi } from "../restoreApi";

vi.mock("../api", () => ({
  api: {
    post: vi.fn(),
    get: vi.fn(),
  },
}));

const mockApi = api as unknown as { post: ReturnType<typeof vi.fn>; get: ReturnType<typeof vi.fn> };

beforeEach(() => {
  vi.clearAllMocks();
});

describe("restoreApi.testVault", () => {
  it("appelle POST /admin/restore/vault/test", async () => {
    mockApi.post.mockResolvedValue({ data: {} });
    await restoreApi.testVault("https://v.test", "key123");
    expect(mockApi.post).toHaveBeenCalledWith("/admin/restore/vault/test", {
      url: "https://v.test",
      api_key: "key123",
    });
  });
});

describe("restoreApi.listSecrets", () => {
  it("appelle GET /admin/restore/vault/secrets avec params", async () => {
    mockApi.get.mockResolvedValue({ data: [] });
    await restoreApi.listSecrets("https://v.test", "key", "certificates");
    expect(mockApi.get).toHaveBeenCalledWith("/admin/restore/vault/secrets", {
      params: {
        vault_url: "https://v.test",
        vault_api_key: "key",
        path: "certificates",
      },
    });
  });
});

describe("restoreApi.startRestore", () => {
  it("retourne le job_id", async () => {
    const jobId = "abc-123";
    mockApi.post.mockResolvedValue({ data: { job_id: jobId } });
    const result = await restoreApi.startRestore({
      connection_type: "sftp",
      manual_fields: {},
      vault_mappings: {},
      vault: { url: "https://v.test", api_key: "k" },
      file_path: "/backups/dump.sql.gz",
    });
    expect(result.job_id).toBe(jobId);
  });
});
