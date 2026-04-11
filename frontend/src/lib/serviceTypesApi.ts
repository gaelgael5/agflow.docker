import { api } from "./api";

export interface ServiceTypeSummary {
  name: string;
  display_name: string;
  is_native: boolean;
  position: number;
  created_at: string;
}

export interface ServiceTypeCreate {
  name: string;
  display_name: string;
}

export const serviceTypesApi = {
  async list(): Promise<ServiceTypeSummary[]> {
    const res = await api.get<ServiceTypeSummary[]>("/admin/service-types");
    return res.data;
  },
  async create(payload: ServiceTypeCreate): Promise<ServiceTypeSummary> {
    const res = await api.post<ServiceTypeSummary>(
      "/admin/service-types",
      payload,
    );
    return res.data;
  },
  async remove(name: string): Promise<void> {
    await api.delete(`/admin/service-types/${name}`);
  },
};
