import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { api } from "@/lib/api";
import { backupsApi } from "@/lib/backupsApi";

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
});

describe("backupsApi", () => {
  it("listLocal GETs /admin/local-backups", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: [
        {
          id: "id1",
          filename: "x.sql.gz",
          size_bytes: 1024,
          status: "completed",
          created_at: "2026-05-14T00:00:00Z",
          source_remote_connection_id: null,
        },
      ],
    });

    const backups = await backupsApi.listLocal();

    expect(api.get).toHaveBeenCalledWith("/admin/local-backups");
    expect(backups[0]?.filename).toBe("x.sql.gz");
  });

  it("listRemoteFiles GETs /admin/backup-remotes/{id}/files", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: [{ filename: "x.sql.gz", size_bytes: 1024, last_modified: null }],
    });

    const files = await backupsApi.listRemoteFiles("conn1");

    expect(api.get).toHaveBeenCalledWith(
      "/admin/backup-remotes/conn1/files",
    );
    expect(files[0]?.filename).toBe("x.sql.gz");
  });

  it("pullFromRemote POSTs filename payload", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      data: {
        id: "id1",
        filename: "x.sql.gz",
        size_bytes: 12,
        status: "completed",
        created_at: "2026-05-14T00:00:00Z",
        source_remote_connection_id: "conn1",
      },
    });

    const result = await backupsApi.pullFromRemote("conn1", "x.sql.gz");

    expect(api.post).toHaveBeenCalledWith(
      "/admin/local-backups/pull-from-remote/conn1",
      { filename: "x.sql.gz" },
    );
    expect(result.source_remote_connection_id).toBe("conn1");
  });

  it("restoreLocal POSTs filename for confirmation", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      data: { backup_id: "b1", exit_code: 0, output_tail: "DONE" },
    });

    const result = await backupsApi.restoreLocal("b1", "x.sql.gz");

    expect(api.post).toHaveBeenCalledWith(
      "/admin/local-backups/b1/restore",
      { filename: "x.sql.gz" },
    );
    expect(result.exit_code).toBe(0);
  });
});
