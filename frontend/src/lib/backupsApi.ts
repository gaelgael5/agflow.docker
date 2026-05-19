import { api } from "./api";

export interface RemoteBackupFile {
  filename: string;
  size_bytes: number | null;
  last_modified: string | null;
}

export type LocalBackupStatus = "in_progress" | "completed" | "failed";

export interface LocalBackup {
  id: string;
  filename: string;
  size_bytes: number | null;
  status: LocalBackupStatus;
  created_at: string;
  source_remote_connection_id: string | null;
  source_kind: "manual" | "full";
}

export interface RestoreResult {
  backup_id: string;
  exit_code: number;
  output_tail: string;
}

export const backupsApi = {
  async listLocal(): Promise<LocalBackup[]> {
    const res = await api.get<LocalBackup[]>("/admin/local-backups");
    return res.data;
  },

  async listRemoteFiles(connectionId: string): Promise<RemoteBackupFile[]> {
    const res = await api.get<RemoteBackupFile[]>(
      `/admin/backup-remotes/${connectionId}/files`,
    );
    return res.data;
  },

  async pullFromRemote(
    connectionId: string,
    filename: string,
  ): Promise<LocalBackup> {
    const res = await api.post<LocalBackup>(
      `/admin/local-backups/pull-from-remote/${connectionId}`,
      { filename },
    );
    return res.data;
  },

  async restoreLocal(
    backupId: string,
    filename: string,
  ): Promise<RestoreResult> {
    const res = await api.post<RestoreResult>(
      `/admin/local-backups/${backupId}/restore`,
      { filename },
    );
    return res.data;
  },
};
