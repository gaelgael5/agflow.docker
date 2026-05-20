import { api } from "./api";

export type PushStatus = "pending" | "pushing" | "ok" | "failed";

export interface LocalBackupPush {
  id: string;
  local_backup_id: string;
  remote_connection_id: string;
  remote_connection_name: string;
  status: PushStatus;
  pushed_at: string | null;
  error: string | null;
  remote_path: string | null;
  size_bytes: number | null;
  created_at: string;
  updated_at: string;
}

export const localBackupPushesApi = {
  listPushes: async (backupId: string): Promise<LocalBackupPush[]> =>
    (await api.get<LocalBackupPush[]>(`/admin/local-backups/${backupId}/pushes`)).data,
  pushBackup: async (backupId: string, remoteId: string): Promise<{ status: string }> =>
    (await api.post<{ status: string }>(`/admin/local-backups/${backupId}/push/${remoteId}`)).data,
};
