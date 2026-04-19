import { api } from "./api";

export interface InstanceSummary {
  id: string;
  instance_name: string;
  catalog_id: string;
  project_id: string;
  variables: Record<string, string>;
  secret_refs: Record<string, string>;
  service_role: string | null;
  status: "draft" | "active" | "stopped";
  service_url: string | null;
}

export interface InstanceCreatePayload {
  instance_name: string;
  catalog_id: string;
  project_id: string;
  variables?: Record<string, string>;
  secret_refs?: Record<string, string>;
  service_role?: string;
}

export interface InstanceUpdatePayload {
  variables?: Record<string, string>;
  secret_refs?: Record<string, string>;
  service_role?: string;
  service_url?: string;
}

export interface GenerateResult {
  generator: string;
  instance_name: string;
  artifact_count: number;
  artifacts: { filename: string; artifact_type: string; size: number }[];
}

export interface BackendInfo {
  catalog_id: string;
  product_name: string;
  connection_url: string;
  status: "configured" | "connected" | "connection_failed";
  mcp_config: Record<string, unknown>;
  openapi_url: string | null;
  openapi_fetched: boolean;
}

export const productInstancesApi = {
  async list(projectId?: string): Promise<InstanceSummary[]> {
    const params = projectId ? `?project_id=${projectId}` : "";
    return (await api.get<InstanceSummary[]>(`/admin/product-instances${params}`)).data;
  },
  async get(projectId: string, instanceId: string): Promise<InstanceSummary> {
    return (await api.get<InstanceSummary>(`/admin/product-instances/${projectId}/${instanceId}`)).data;
  },
  async create(p: InstanceCreatePayload): Promise<InstanceSummary> {
    return (await api.post<InstanceSummary>("/admin/product-instances", p)).data;
  },
  async update(projectId: string, instanceId: string, p: InstanceUpdatePayload): Promise<InstanceSummary> {
    return (await api.put<InstanceSummary>(`/admin/product-instances/${projectId}/${instanceId}`, p)).data;
  },
  async remove(projectId: string, instanceId: string): Promise<void> {
    await api.delete(`/admin/product-instances/${projectId}/${instanceId}`);
  },
  async activate(projectId: string, instanceId: string, serviceUrl: string): Promise<InstanceSummary> {
    return (await api.post<InstanceSummary>(`/admin/product-instances/${projectId}/${instanceId}/activate`, { service_url: serviceUrl })).data;
  },
  async stop(projectId: string, instanceId: string): Promise<InstanceSummary> {
    return (await api.post<InstanceSummary>(`/admin/product-instances/${projectId}/${instanceId}/stop`)).data;
  },
  async generate(projectId: string, instanceId: string, generator: string = "docker_compose"): Promise<GenerateResult> {
    return (await api.post<GenerateResult>(`/admin/product-instances/${projectId}/${instanceId}/generate`, { generator })).data;
  },
  async downloadZip(projectId: string, instanceId: string, generator: string = "docker_compose"): Promise<Blob> {
    const res = await api.post(`/admin/product-instances/${projectId}/${instanceId}/generate/download`, { generator }, { responseType: "blob" });
    return res.data as Blob;
  },
  async getBackend(projectId: string, instanceId: string): Promise<BackendInfo | null> {
    try {
      return (await api.get<BackendInfo>(`/admin/product-instances/${projectId}/${instanceId}/backend`)).data;
    } catch {
      return null;
    }
  },
  async refreshOpenapi(projectId: string, instanceId: string): Promise<{ status: string; openapi_fetched: boolean }> {
    return (await api.post(`/admin/product-instances/${projectId}/${instanceId}/refresh-openapi`)).data;
  },
};
