import { api } from "./api";

export type ServiceType = "image_generation" | "embedding" | "llm";

export interface ProviderSummary {
  service_type: ServiceType;
  provider_name: string;
  display_name: string;
  secret_ref: string;
  enabled: boolean;
  is_default: boolean;
}

export interface ProviderCreatePayload {
  service_type: ServiceType;
  provider_name: string;
  display_name: string;
  secret_ref?: string;
  enabled?: boolean;
  is_default?: boolean;
}

export interface ProviderUpdatePayload {
  display_name?: string;
  secret_ref?: string;
  enabled?: boolean;
  is_default?: boolean;
}

export const aiProvidersApi = {
  async list(serviceType?: ServiceType): Promise<ProviderSummary[]> {
    const params = serviceType ? `?service_type=${serviceType}` : "";
    return (await api.get<ProviderSummary[]>(`/admin/ai-providers${params}`)).data;
  },
  async create(p: ProviderCreatePayload): Promise<ProviderSummary> {
    return (await api.post<ProviderSummary>("/admin/ai-providers", p)).data;
  },
  async update(serviceType: string, providerName: string, p: ProviderUpdatePayload): Promise<ProviderSummary> {
    return (await api.put<ProviderSummary>(`/admin/ai-providers/${serviceType}/${providerName}`, p)).data;
  },
  async remove(serviceType: string, providerName: string): Promise<void> {
    await api.delete(`/admin/ai-providers/${serviceType}/${providerName}`);
  },
};
