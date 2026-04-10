import { api } from "./api";

export type Transport = "stdio" | "sse" | "docker";

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

export interface MCPSearchItem {
  package_id: string;
  name: string;
  repo: string;
  repo_url: string;
  transport: Transport;
  short_description: string;
  long_description: string;
  documentation_url: string;
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
  parameters: Record<string, unknown>;
  parameters_schema: Array<Record<string, unknown>>;
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
    semantic: boolean,
  ): Promise<MCPSearchItem[]> {
    const res = await api.get<MCPSearchItem[]>(
      `/admin/discovery-services/${id}/search/mcp`,
      { params: { q: query, semantic: semantic ? "1" : "0" } },
    );
    return res.data;
  },
  async searchSkills(id: string, query: string): Promise<SkillSearchItem[]> {
    const res = await api.get<SkillSearchItem[]>(
      `/admin/discovery-services/${id}/search/skills`,
      { params: { q: query } },
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
    discoveryServiceId: string,
    packageId: string,
  ): Promise<MCPServerSummary> {
    const res = await api.post<MCPServerSummary>("/admin/mcp-catalog", {
      discovery_service_id: discoveryServiceId,
      package_id: packageId,
    });
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
