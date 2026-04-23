import { api } from "./api";

export interface RegistrySummary {
  id: string;
  display_name: string;
  url: string;
  auth_type: "none" | "basic" | "token";
  credential_ref: string | null;
  is_default: boolean;
}

export interface RegistryCreatePayload {
  id: string;
  display_name: string;
  url: string;
  auth_type?: "none" | "basic" | "token";
  credential_ref?: string;
}

export interface RegistryUpdatePayload {
  display_name?: string;
  url?: string;
  auth_type?: "none" | "basic" | "token";
  credential_ref?: string | null;
}

export const imageRegistriesApi = {
  async list(): Promise<RegistrySummary[]> {
    return (await api.get<RegistrySummary[]>("/admin/image-registries")).data;
  },
  async get(id: string): Promise<RegistrySummary> {
    return (await api.get<RegistrySummary>(`/admin/image-registries/${id}`)).data;
  },
  async create(p: RegistryCreatePayload): Promise<RegistrySummary> {
    return (await api.post<RegistrySummary>("/admin/image-registries", p)).data;
  },
  async update(id: string, p: RegistryUpdatePayload): Promise<RegistrySummary> {
    return (await api.put<RegistrySummary>(`/admin/image-registries/${id}`, p)).data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/image-registries/${id}`);
  },
};
