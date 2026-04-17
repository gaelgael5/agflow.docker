import { api } from "./api";

export type Transport = "stdio" | "sse" | "docker" | "streamable-http";

export interface DiscoveryServiceSummary {
  id: string;
  name: string;
  base_url: string;
  api_key_var: string | null;
  description: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface DiscoveryServiceCreate {
  id: string;
  name: string;
  base_url: string;
  api_key_var?: string | null;
  description?: string;
  enabled?: boolean;
}

export interface ProbeResult {
  ok: boolean;
  detail: string;
}

export interface TargetMode {
  runtime: string;
  action_type: "cmd" | "insert_in_file";
  template: string;
  config_path?: string;
}

export interface TargetSummary {
  id: string;
  name: string;
  description: string;
  modes: TargetMode[];
  skill_modes: unknown[];
}

export interface MCPSearchItem {
  package_id: string;
  name: string;
  repo: string;
  repo_url: string;
  transport: Transport;
  category: string;
  short_description: string;
  long_description: string;
  documentation_url: string;
  has_summaries: boolean;
  recipes: Record<string, { action_type: string; data: string; config_path?: string }>;
  parameters: Array<{ name: string; description: string; is_required: boolean; is_secret: boolean }>;
}

export interface MCPServerSummary {
  id: string;
  discovery_service_id: string;
  package_id: string;
  name: string;
  repo: string;
  repo_url: string;
  transport: Transport;
  short_description: string;
  long_description: string;
  documentation_url: string;
  parameters: Array<{ name: string; description: string; is_required: boolean; is_secret: boolean }>;
  parameters_schema: Array<Record<string, unknown>>;
  recipes: Record<string, { action_type: string; data: string; config_path?: string }>;
  created_at: string;
  updated_at: string;
}

export interface SkillSearchItem {
  skill_id: string;
  name: string;
  description: string;
}

export interface SkillSummary {
  id: string;
  discovery_service_id: string;
  skill_id: string;
  name: string;
  description: string;
  content_md: string;
  created_at: string;
  updated_at: string;
}

export const discoveryApi = {
  async list(): Promise<DiscoveryServiceSummary[]> {
    const res = await api.get<DiscoveryServiceSummary[]>("/admin/discovery-services");
    return res.data;
  },
  async create(payload: DiscoveryServiceCreate): Promise<DiscoveryServiceSummary> {
    const res = await api.post<DiscoveryServiceSummary>(
      "/admin/discovery-services",
      payload,
    );
    return res.data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/discovery-services/${id}`);
  },
  async test(id: string): Promise<ProbeResult> {
    const res = await api.post<ProbeResult>(`/admin/discovery-services/${id}/test`);
    return res.data;
  },
  async searchMcp(
    id: string,
    query: string,
    semantic: boolean = false,
  ): Promise<MCPSearchItem[]> {
    const res = await api.get<MCPSearchItem[]>(
      `/admin/discovery-services/${id}/search/mcp`,
      { params: { q: query, semantic: semantic ? "1" : "0" } },
    );
    return res.data;
  },
  async getSummary(
    serviceId: string,
    packageId: string,
    culture: string = "fr",
  ): Promise<string | null> {
    try {
      const res = await api.get<{ summary: string }>(
        `/admin/discovery-services/${serviceId}/summary/${packageId}`,
        { params: { culture } },
      );
      return res.data.summary;
    } catch {
      return null;
    }
  },
  async searchSkills(id: string, query: string): Promise<SkillSearchItem[]> {
    const res = await api.get<SkillSearchItem[]>(
      `/admin/discovery-services/${id}/search/skills`,
      { params: { q: query } },
    );
    return res.data;
  },
  async fetchTargets(serviceId: string): Promise<TargetSummary[]> {
    const res = await api.get<TargetSummary[]>(
      `/admin/discovery-services/${serviceId}/targets`,
    );
    return res.data;
  },
};

export const mcpCatalogApi = {
  async list(): Promise<MCPServerSummary[]> {
    const res = await api.get<MCPServerSummary[]>("/admin/mcp-catalog");
    return res.data;
  },
  async install(
    payload: {
      discovery_service_id: string;
      package_id: string;
      recipes?: Record<string, unknown>;
      parameters?: unknown[];
    },
  ): Promise<MCPServerSummary> {
    const res = await api.post<MCPServerSummary>("/admin/mcp-catalog", payload);
    return res.data;
  },
  async updateParameters(
    id: string,
    parameters: Record<string, unknown>,
  ): Promise<MCPServerSummary> {
    const res = await api.put<MCPServerSummary>(`/admin/mcp-catalog/${id}`, {
      parameters,
    });
    return res.data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/mcp-catalog/${id}`);
  },
};

export const skillsCatalogApi = {
  async list(): Promise<SkillSummary[]> {
    const res = await api.get<SkillSummary[]>("/admin/skills-catalog");
    return res.data;
  },
  async install(
    discoveryServiceId: string,
    skillId: string,
  ): Promise<SkillSummary> {
    const res = await api.post<SkillSummary>("/admin/skills-catalog", {
      discovery_service_id: discoveryServiceId,
      skill_id: skillId,
    });
    return res.data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/skills-catalog/${id}`);
  },
};
