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
  is_assistant: boolean;
  created_at: string;
  updated_at: string;
  has_errors: boolean;
}

export interface AgentProfileSummary {
  id: string;
  agent_id: string;
  name: string;
  description: string;
  document_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface AgentProfileCreate {
  name: string;
  description?: string;
  document_ids?: string[];
}

export interface AgentProfileUpdate {
  name?: string;
  description?: string;
  document_ids?: string[];
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
  profile_name: string | null;
  broken_document_ids: string[];
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

  configPreview: async (
    id: string,
    profileId?: string,
  ): Promise<ConfigPreview> => {
    const res = await api.get<ConfigPreview>(
      `/admin/agents/${id}/config-preview`,
      profileId ? { params: { profile_id: profileId } } : undefined,
    );
    return res.data;
  },

  listProfiles: async (agentId: string): Promise<AgentProfileSummary[]> => {
    const res = await api.get<AgentProfileSummary[]>(
      `/admin/agents/${agentId}/profiles`,
    );
    return res.data;
  },

  createProfile: async (
    agentId: string,
    payload: AgentProfileCreate,
  ): Promise<AgentProfileSummary> => {
    const res = await api.post<AgentProfileSummary>(
      `/admin/agents/${agentId}/profiles`,
      payload,
    );
    return res.data;
  },

  updateProfile: async (
    agentId: string,
    profileId: string,
    payload: AgentProfileUpdate,
  ): Promise<AgentProfileSummary> => {
    const res = await api.put<AgentProfileSummary>(
      `/admin/agents/${agentId}/profiles/${profileId}`,
      payload,
    );
    return res.data;
  },

  deleteProfile: async (agentId: string, profileId: string): Promise<void> => {
    await api.delete(`/admin/agents/${agentId}/profiles/${profileId}`);
  },

  getAssistant: async (): Promise<AgentSummary | null> => {
    const res = await api.get<AgentSummary | null>("/admin/agents/assistant");
    return res.data;
  },

  setAssistant: async (agentId: string): Promise<void> => {
    await api.post(`/admin/agents/${agentId}/set-assistant`);
  },

  clearAssistant: async (): Promise<void> => {
    await api.delete("/admin/agents/assistant");
  },

  listGenerated: async (agentId: string): Promise<{ path: string; content: string }[]> => {
    const res = await api.get<{ path: string; content: string }[]>(
      `/admin/agents/${agentId}/generated`,
    );
    return res.data;
  },

  generate: async (
    agentId: string,
    payload?: { profile_id?: string; secrets?: Record<string, string> },
  ): Promise<{ slug: string; path: string; files: string[] }> => {
    const res = await api.post(`/admin/agents/${agentId}/generate`, payload ?? {});
    return res.data;
  },

  importZip: async (file: File): Promise<AgentDetail> => {
    const form = new FormData();
    form.append("file", file);
    const res = await api.post<AgentDetail>("/admin/agents/import", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return res.data;
  },

  exportZip: async (agentId: string): Promise<Blob> => {
    const res = await api.get(`/admin/agents/${agentId}/export`, {
      responseType: "blob",
    });
    return res.data as Blob;
  },
};
