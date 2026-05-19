import { api } from "./api";

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

export interface ScheduleHistoryEntry {
  id: string;
  filename: string;
  file_path: string;
  size_bytes: number | null;
  status: "in_progress" | "completed" | "failed";
  created_at: string;
  created_by_user_id: string | null;
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
  async listFullHistory(id: string, limit = 50): Promise<ScheduleHistoryEntry[]> {
    const r = await api.get<ScheduleHistoryEntry[]>(
      `/admin/backup-schedules/full/${id}/history?limit=${limit}`,
    );
    return r.data;
  },

};
