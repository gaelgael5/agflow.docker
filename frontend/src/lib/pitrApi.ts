import { api } from "./api";

export type PushStatus = "pending" | "pushing" | "ok" | "failed";
export type BasebackupStatus = "running" | "ok" | "failed";
export type CloneStatusValue =
  | "restoring"
  | "ready"
  | "terminating"
  | "terminated"
  | "failed";

export interface BasebackupPushSummary {
  remote_connection_id: string;
  remote_connection_name: string;
  status: PushStatus;
  pushed_at: string | null;
  error: string | null;
  size_bytes: number | null;
}

export interface BasebackupSummary {
  id: string;
  pgbackrest_label: string;
  started_at: string;
  completed_at: string | null;
  size_bytes: number | null;
  status: BasebackupStatus;
  error: string | null;
  recovery_window_start: string | null;
  recovery_window_end: string | null;
  pushes: BasebackupPushSummary[];
}

export type BasebackupType = "full" | "diff" | "incr";

export interface PitrConfig {
  enabled: boolean;
  basebackup_cron: string;
  basebackup_type: BasebackupType;
  full_rebase_cron: string;
  retention_count: number;
  remote_connection_ids: string[];
  updated_at: string;
}

export interface PitrConfigUpdate {
  enabled?: boolean;
  basebackup_cron?: string;
  basebackup_type?: BasebackupType;
  full_rebase_cron?: string;
  retention_count?: number;
  remote_connection_ids?: string[];
}

export interface WalStatus {
  archiving_enabled: boolean;
  last_archived_at: string | null;
  archive_lag_seconds: number | null;
  wal_disk_used_bytes: number;
  wal_disk_free_bytes: number;
}

export interface RestoreWindow {
  earliest: string;
  latest: string;
}

export interface CloneStatusOut {
  id: string;
  basebackup_id: string;
  basebackup_label: string;
  target_time: string;
  status: CloneStatusValue;
  error: string | null;
  pgweb_url: string | null;
  started_at: string;
  ready_at: string | null;
  expires_at: string;
  expires_in_seconds: number;
}

export const pitrApi = {
  // --- Config ---
  getConfig: async (): Promise<PitrConfig> => {
    const r = await api.get<PitrConfig>("/admin/pitr/config");
    return r.data;
  },
  updateConfig: async (payload: PitrConfigUpdate): Promise<PitrConfig> => {
    const r = await api.put<PitrConfig>("/admin/pitr/config", payload);
    return r.data;
  },

  // --- Basebackups ---
  listBasebackups: async (): Promise<BasebackupSummary[]> => {
    const r = await api.get<BasebackupSummary[]>("/admin/pitr/basebackups");
    return r.data;
  },
  getBasebackup: async (id: string): Promise<BasebackupSummary> => {
    const r = await api.get<BasebackupSummary>(`/admin/pitr/basebackups/${id}`);
    return r.data;
  },
  triggerBasebackup: async (): Promise<{ id: string }> => {
    const r = await api.post<{ id: string }>("/admin/pitr/basebackups");
    return r.data;
  },
  deleteBasebackup: async (id: string): Promise<void> => {
    await api.delete(`/admin/pitr/basebackups/${id}`);
  },
  pushBasebackup: async (
    basebackupId: string,
    remoteId: string,
  ): Promise<{ status: string }> => {
    const r = await api.post<{ status: string }>(
      `/admin/pitr/basebackups/${basebackupId}/push/${remoteId}`,
    );
    return r.data;
  },

  // --- WAL + Restore Window ---
  getWalStatus: async (): Promise<WalStatus> => {
    const r = await api.get<WalStatus>("/admin/pitr/wal-status");
    return r.data;
  },
  getRestoreWindow: async (): Promise<RestoreWindow> => {
    const r = await api.get<RestoreWindow>("/admin/pitr/restore-window");
    return r.data;
  },

  // --- Clones ---
  startClone: async (targetTime: string): Promise<{ id: string }> => {
    const r = await api.post<{ id: string }>("/admin/pitr/clones", {
      target_time: targetTime,
    });
    return r.data;
  },
  getActiveClone: async (): Promise<CloneStatusOut | null> => {
    const r = await api.get<CloneStatusOut | null>("/admin/pitr/clones/active");
    return r.data;
  },
  extendActiveClone: async (): Promise<CloneStatusOut> => {
    const r = await api.post<CloneStatusOut>("/admin/pitr/clones/active/extend");
    return r.data;
  },
  terminateActiveClone: async (): Promise<void> => {
    await api.delete("/admin/pitr/clones/active");
  },
};
