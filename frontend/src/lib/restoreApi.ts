// frontend/src/lib/restoreApi.ts
import { api } from "./api";

export interface VaultSecretItem {
  name: string;
  tags: string[];
}

export interface RemoteEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size_bytes: number | null;
  modified_at: string | null;
}

export interface RemoteBrowseRequest {
  connection_type: "sftp" | "s3" | "ftps" | "gdrive";
  manual_fields: Record<string, string>;
  vault_mappings: Record<string, string>;
  vault: { url: string; api_key: string };
  path?: string;
}

export interface RestoreExecuteRequest {
  connection_type: "sftp" | "s3" | "ftps" | "gdrive";
  manual_fields: Record<string, string>;
  vault_mappings: Record<string, string>;
  vault: { url: string; api_key: string };
  file_path: string;
}

export interface RestoreJobStatus {
  job_id: string;
  status: "running" | "done" | "failed";
  log: string;
  created_at: string;
  completed_at: string | null;
}

export const restoreApi = {
  async testVault(url: string, apiKey: string): Promise<void> {
    await api.post("/admin/restore/vault/test", { url, api_key: apiKey });
  },

  async listSecrets(
    vaultUrl: string,
    vaultApiKey: string,
    path: string,
  ): Promise<VaultSecretItem[]> {
    const res = await api.post<VaultSecretItem[]>("/admin/restore/vault/secrets", {
      url: vaultUrl,
      api_key: vaultApiKey,
      path,
    });
    return res.data;
  },

  async browse(body: RemoteBrowseRequest): Promise<RemoteEntry[]> {
    const res = await api.post<RemoteEntry[]>("/admin/restore/remote/browse", body);
    return res.data;
  },

  async startRestore(body: RestoreExecuteRequest): Promise<{ job_id: string }> {
    const res = await api.post<{ job_id: string }>("/admin/restore/execute", body);
    return res.data;
  },

  async getJobStatus(jobId: string): Promise<RestoreJobStatus> {
    const res = await api.get<RestoreJobStatus>(`/admin/restore/execute/${jobId}`);
    return res.data;
  },
};
