import { AxiosError } from "axios";
import { api } from "./api";

export type AuthMode = "ssh_key" | "pat_https" | "basic_https";
export type RunStatus = "ok" | "failed";

export interface GitSyncConfig {
  repo_url: string;
  auth_mode: AuthMode;
  auth_secret_ref: string;
  branch: string;
  commit_author_name: string;
  commit_author_email: string;
  excluded_columns: Record<string, string[]>;
  selected_tables: string[];
  cron_expr: string | null;
  cron_enabled: boolean;
  last_export_at: string | null;
  last_export_status: RunStatus | null;
  last_export_sha: string | null;
  last_export_error: string | null;
  last_export_tables_count: number | null;
  last_import_at: string | null;
  last_import_status: RunStatus | null;
  last_import_error: string | null;
  last_import_rows_inserted: number | null;
  last_import_rows_updated: number | null;
  last_import_rows_deleted: number | null;
  created_at: string;
  updated_at: string;
}

export interface GitSyncConfigUpsert {
  repo_url: string;
  auth_mode: AuthMode;
  auth_secret_ref: string;
  branch: string;
  commit_author_name: string;
  commit_author_email: string;
  excluded_columns: Record<string, string[]>;
  selected_tables: string[];
  cron_expr: string | null;
  cron_enabled: boolean;
}

export interface GitSyncTestSecretRefResult {
  ok: boolean;
  error: string | null;
}

export interface GitSyncExportResult {
  sha: string;
  tables_count: number;
}

export interface GitSyncTablePreview {
  table: string;
  to_insert: number;
  to_update: number;
  to_delete: number;
}

export interface GitSyncImportPreview {
  tables: GitSyncTablePreview[];
}

export interface GitSyncImportResult {
  rows_inserted: number;
  rows_updated: number;
  rows_deleted: number;
}

export interface GitSyncCommit {
  sha: string;
  short_sha: string;
  message: string;
  author_name: string;
  author_email: string;
  authored_at: string;
  html_url: string;
}

const BASE = "/admin/git-sync";

export const gitSyncApi = {
  async fetchConfig(): Promise<GitSyncConfig | null> {
    try {
      const res = await api.get<GitSyncConfig>(`${BASE}/config`);
      return res.data;
    } catch (err) {
      if (err instanceof AxiosError && err.response?.status === 404) {
        return null;
      }
      throw err;
    }
  },

  async upsertConfig(payload: GitSyncConfigUpsert): Promise<GitSyncConfig> {
    const res = await api.put<GitSyncConfig>(`${BASE}/config`, payload);
    return res.data;
  },

  async deleteConfig(): Promise<void> {
    await api.delete(`${BASE}/config`);
  },

  async listAvailableTables(): Promise<string[]> {
    const res = await api.get<string[]>(`${BASE}/available-tables`);
    return res.data;
  },

  async testSecretRef(
    authSecretRef: string,
  ): Promise<GitSyncTestSecretRefResult> {
    const res = await api.post<GitSyncTestSecretRefResult>(
      `${BASE}/test-secret-ref`,
      { auth_secret_ref: authSecretRef },
    );
    return res.data;
  },

  async runExport(): Promise<GitSyncExportResult> {
    const res = await api.post<GitSyncExportResult>(`${BASE}/export`);
    return res.data;
  },

  async previewImport(): Promise<GitSyncImportPreview> {
    const res = await api.post<GitSyncImportPreview>(`${BASE}/preview-import`);
    return res.data;
  },

  async runImport(): Promise<GitSyncImportResult> {
    const res = await api.post<GitSyncImportResult>(`${BASE}/import`);
    return res.data;
  },

  async listCommits(limit = 30): Promise<GitSyncCommit[]> {
    const res = await api.get<GitSyncCommit[]>(`${BASE}/commits`, {
      params: { limit },
    });
    return res.data;
  },
};
