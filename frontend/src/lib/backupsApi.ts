import { api } from "./api";
import type { LocalBackupPush } from "./localBackupPushesApi";

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
  local_file_present: boolean;
  pushes: LocalBackupPush[];
}

export interface RestoreResult {
  backup_id: string;
  exit_code: number;
  output_tail: string;
}

export interface ScanResult {
  imported: number;
  skipped: number;
  errors: string[];
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

  async scanFromSchedules(): Promise<ScanResult> {
    const res = await api.post<ScanResult>("/admin/local-backups/scan-schedules");
    return res.data;
  },
};
