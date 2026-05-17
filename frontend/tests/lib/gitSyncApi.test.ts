import { describe, it, expect, vi, beforeEach } from "vitest";
import { AxiosError, type AxiosResponse } from "axios";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

import { api } from "@/lib/api";
import { gitSyncApi } from "@/lib/gitSyncApi";

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
  vi.mocked(api.put).mockReset();
  vi.mocked(api.delete).mockReset();
});

describe("gitSyncApi.fetchConfig", () => {
  it("returns null on 404", async () => {
    const err = new AxiosError("Not Found");
    err.response = { status: 404 } as AxiosResponse;
    vi.mocked(api.get).mockRejectedValueOnce(err);

    const result = await gitSyncApi.fetchConfig();

    expect(result).toBeNull();
    expect(api.get).toHaveBeenCalledWith("/admin/git-sync/config");
  });

  it("returns parsed config on 200", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: {
        repo_url: "https://github.com/owner/repo",
        auth_mode: "pat_https",
        auth_secret_ref: "${vault://default:git/pat}",
        branch: "main",
        commit_author_name: "bot",
        commit_author_email: "bot@local",
        excluded_columns: {},
        selected_tables: ["users"],
        cron_expr: null,
        cron_enabled: false,
        last_export_at: null,
        last_export_status: null,
        last_export_sha: null,
        last_export_error: null,
        last_export_tables_count: null,
        last_import_at: null,
        last_import_status: null,
        last_import_error: null,
        last_import_rows_inserted: null,
        last_import_rows_updated: null,
        last_import_rows_deleted: null,
        created_at: "2026-05-17T00:00:00Z",
        updated_at: "2026-05-17T00:00:00Z",
      },
    });

    const result = await gitSyncApi.fetchConfig();

    expect(result?.repo_url).toBe("https://github.com/owner/repo");
  });
});

describe("gitSyncApi.testSecretRef", () => {
  it("posts ref to /test-secret-ref", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      data: { ok: true, error: null },
    });

    const result = await gitSyncApi.testSecretRef(
      "${vault://default:git/pat}",
    );

    expect(result.ok).toBe(true);
    expect(api.post).toHaveBeenCalledWith(
      "/admin/git-sync/test-secret-ref",
      { auth_secret_ref: "${vault://default:git/pat}" },
    );
  });
});
