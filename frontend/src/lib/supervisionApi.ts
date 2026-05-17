import { z } from "zod";
import { api } from "./api";

export const SessionStatusCountsSchema = z.object({
  active: z.number(),
  closed: z.number(),
  expired: z.number(),
});

export const AgentStatusCountsSchema = z.object({
  idle: z.number(),
  busy: z.number(),
  error: z.number(),
  destroyed_total: z.number(),
});

export const MomDeliveryCountsSchema = z.object({
  pending: z.number(),
  claimed: z.number(),
  failed: z.number(),
});

export const SupervisionOverviewSchema = z.object({
  sessions: SessionStatusCountsSchema,
  agents: AgentStatusCountsSchema,
  containers_running: z.number().nullable(),
  mom: MomDeliveryCountsSchema,
});

export const SupervisedInstanceSchema = z.object({
  id: z.string().uuid(),
  session_id: z.string().uuid(),
  agent_id: z.string(),
  mission: z.string().nullable(),
  status: z.string(),
  last_activity_at: z.string(),
  created_at: z.string(),
  destroyed_at: z.string().nullable(),
  error_message: z.string().nullable(),
  last_container_name: z.string().nullable(),
});

export const InstanceDetailSchema = SupervisedInstanceSchema.extend({
  labels: z.record(z.string(), z.unknown()),
  container_status: z.string().nullable(),
  mom_counts: MomDeliveryCountsSchema,
  recent_messages: z.array(z.record(z.string(), z.unknown())),
});

export type SupervisionOverview = z.infer<typeof SupervisionOverviewSchema>;
export type SupervisedInstance = z.infer<typeof SupervisedInstanceSchema>;
export type InstanceDetail = z.infer<typeof InstanceDetailSchema>;

export type InstanceStatusFilter =
  | "all"
  | "idle"
  | "busy"
  | "error"
  | "destroyed";

export interface ListInstancesParams {
  status?: "idle" | "busy" | "error" | "destroyed";
  limit?: number;
}

export const supervisionApi = {
  async getOverview(): Promise<SupervisionOverview> {
    const res = await api.get<unknown>("/admin/supervision/overview");
    return SupervisionOverviewSchema.parse(res.data);
  },

  async listInstances(
    params: ListInstancesParams = {},
  ): Promise<SupervisedInstance[]> {
    const qs = new URLSearchParams();
    if (params.status) qs.set("status", params.status);
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    const path = qs.toString()
      ? `/admin/supervision/instances?${qs.toString()}`
      : "/admin/supervision/instances";
    const res = await api.get<unknown>(path);
    return z.array(SupervisedInstanceSchema).parse(res.data);
  },

  async getInstance(id: string): Promise<InstanceDetail> {
    const res = await api.get<unknown>(`/admin/supervision/instances/${id}`);
    return InstanceDetailSchema.parse(res.data);
  },
};
