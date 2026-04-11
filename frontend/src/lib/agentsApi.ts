import { api } from "./api";

export type NetworkMode = "bridge" | "host" | "none";
export type ImageStatus = "missing" | "stale" | "fresh";

export interface AgentMCPBinding {
  mcp_server_id: string;
  parameters_override: Record<string, unknown>;
  position: number;
}

export interface AgentSkillBinding {
  skill_id: string;
  position: number;
}

export interface AgentSummary {
  id: string;
  slug: string;
  display_name: string;
  description: string;
  dockerfile_id: string;
  role_id: string;
  env_vars: Record<string, string>;
  timeout_seconds: number;
  workspace_path: string;
  network_mode: NetworkMode;
  graceful_shutdown_secs: number;
  force_kill_delay_secs: number;
  created_at: string;
  updated_at: string;
}

export interface AgentDetail extends AgentSummary {
  mcp_bindings: AgentMCPBinding[];
  skill_bindings: AgentSkillBinding[];
  image_status: ImageStatus;
}

export interface AgentCreatePayload {
  slug: string;
  display_name: string;
  description?: string;
  dockerfile_id: string;
  role_id: string;
  env_vars?: Record<string, string>;
  timeout_seconds?: number;
  workspace_path?: string;
  network_mode?: NetworkMode;
  graceful_shutdown_secs?: number;
  force_kill_delay_secs?: number;
  mcp_bindings?: AgentMCPBinding[];
  skill_bindings?: AgentSkillBinding[];
}

export type AgentUpdatePayload = Omit<AgentCreatePayload, "slug">;

export interface SkillPreview {
  skill_id: string;
  name: string;
  content_md: string;
}

export interface ConfigPreview {
  prompt_md: string;
  mcp_json: { mcpServers: Record<string, unknown> };
  tools_json: Array<Record<string, unknown>>;
  env_file: string;
  skills: SkillPreview[];
  validation_errors: string[];
  image_status: ImageStatus;
}

export const agentsApi = {
  list: async (): Promise<AgentSummary[]> => {
    const res = await api.get<AgentSummary[]>("/admin/agents");
    return res.data;
  },

  get: async (id: string): Promise<AgentDetail> => {
    const res = await api.get<AgentDetail>(`/admin/agents/${id}`);
    return res.data;
  },

  create: async (payload: AgentCreatePayload): Promise<AgentDetail> => {
    const res = await api.post<AgentDetail>("/admin/agents", payload);
    return res.data;
  },

  update: async (
    id: string,
    payload: AgentUpdatePayload,
  ): Promise<AgentDetail> => {
    const res = await api.put<AgentDetail>(`/admin/agents/${id}`, payload);
    return res.data;
  },

  remove: async (id: string): Promise<void> => {
    await api.delete(`/admin/agents/${id}`);
  },

  duplicate: async (
    id: string,
    slug: string,
    display_name: string,
  ): Promise<AgentDetail> => {
    const res = await api.post<AgentDetail>(`/admin/agents/${id}/duplicate`, {
      slug,
      display_name,
    });
    return res.data;
  },

  configPreview: async (id: string): Promise<ConfigPreview> => {
    const res = await api.get<ConfigPreview>(
      `/admin/agents/${id}/config-preview`,
    );
    return res.data;
  },
};
