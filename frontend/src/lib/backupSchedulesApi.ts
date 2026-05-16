import { api } from "./api";

export type ScheduleKind = "full" | "snapshot";

export interface FullScheduleSummary {
  id: string;
  name: string;
  cron_expr: string;
  remote_connection_id: string | null;
  retention_count: number;
  enabled: boolean;
  last_run_at: string | null;
  last_run_status: "ok" | "failed" | null;
  last_run_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SnapshotScheduleSummary {
  id: string;
  name: string;
  interval_amount: number;
  interval_unit: "minutes" | "hours";
  remote_connection_id: string | null;
  retention_count: number;
  enabled: boolean;
  last_run_at: string | null;
  last_run_status: "ok" | "failed" | null;
  last_run_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateFullPayload {
  name: string;
  cron_expr: string;
  remote_connection_id?: string | null;
  retention_count?: number;
  enabled?: boolean;
}

export interface UpdateFullPayload {
  name?: string;
  cron_expr?: string;
  remote_connection_id?: string | null;
  retention_count?: number;
  enabled?: boolean;
}

export interface CreateSnapshotPayload {
  name: string;
  interval_amount: number;
  interval_unit: "minutes" | "hours";
  remote_connection_id?: string | null;
  retention_count?: number;
  enabled?: boolean;
}

export interface UpdateSnapshotPayload {
  name?: string;
  interval_amount?: number;
  interval_unit?: "minutes" | "hours";
  remote_connection_id?: string | null;
  retention_count?: number;
  enabled?: boolean;
}

export const backupSchedulesApi = {
  // Full
  async listFull(): Promise<FullScheduleSummary[]> {
    const r = await api.get<FullScheduleSummary[]>("/admin/backup-schedules/full");
    return r.data;
  },
  async createFull(payload: CreateFullPayload): Promise<FullScheduleSummary> {
    const r = await api.post<FullScheduleSummary>("/admin/backup-schedules/full", payload);
    return r.data;
  },
  async updateFull(id: string, payload: UpdateFullPayload): Promise<FullScheduleSummary> {
    const r = await api.put<FullScheduleSummary>(`/admin/backup-schedules/full/${id}`, payload);
    return r.data;
  },
  async removeFull(id: string): Promise<void> {
    await api.delete(`/admin/backup-schedules/full/${id}`);
  },
  async runFullNow(id: string): Promise<void> {
    await api.post(`/admin/backup-schedules/full/${id}/run-now`);
  },
  async setFullEnabled(id: string, enabled: boolean): Promise<FullScheduleSummary> {
    const r = await api.post<FullScheduleSummary>(
      `/admin/backup-schedules/full/${id}/set-enabled`,
      { enabled },
    );
    return r.data;
  },

  // Snapshot
  async listSnapshot(): Promise<SnapshotScheduleSummary[]> {
    const r = await api.get<SnapshotScheduleSummary[]>("/admin/backup-schedules/snapshot");
    return r.data;
  },
  async createSnapshot(payload: CreateSnapshotPayload): Promise<SnapshotScheduleSummary> {
    const r = await api.post<SnapshotScheduleSummary>("/admin/backup-schedules/snapshot", payload);
    return r.data;
  },
  async updateSnapshot(id: string, payload: UpdateSnapshotPayload): Promise<SnapshotScheduleSummary> {
    const r = await api.put<SnapshotScheduleSummary>(`/admin/backup-schedules/snapshot/${id}`, payload);
    return r.data;
  },
  async removeSnapshot(id: string): Promise<void> {
    await api.delete(`/admin/backup-schedules/snapshot/${id}`);
  },
  async runSnapshotNow(id: string): Promise<void> {
    await api.post(`/admin/backup-schedules/snapshot/${id}/run-now`);
  },
  async setSnapshotEnabled(id: string, enabled: boolean): Promise<SnapshotScheduleSummary> {
    const r = await api.post<SnapshotScheduleSummary>(
      `/admin/backup-schedules/snapshot/${id}/set-enabled`,
      { enabled },
    );
    return r.data;
  },
};
