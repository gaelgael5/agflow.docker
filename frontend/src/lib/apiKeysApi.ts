import { api } from "./api";

export interface ApiKeySummary {
  id: string;
  owner_id: string;
  name: string;
  prefix: string;
  scopes: string[];
  rate_limit: number | null;
  expires_at: string | null;
  revoked: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface ApiKeyCreated extends ApiKeySummary {
  full_key: string;
}

export interface ApiKeyCreate {
  name: string;
  scopes: string[];
  rate_limit?: number;
  expires_in?: string;
}

export interface ApiKeyUpdate {
  name?: string;
  scopes?: string[];
  rate_limit?: number;
}

export const apiKeysApi = {
  async list(): Promise<ApiKeySummary[]> {
    const res = await api.get<ApiKeySummary[]>("/admin/api-keys");
    return res.data;
  },

  async get(id: string): Promise<ApiKeySummary> {
    const res = await api.get<ApiKeySummary>(`/admin/api-keys/${id}`);
    return res.data;
  },

  async create(payload: ApiKeyCreate): Promise<ApiKeyCreated> {
    const res = await api.post<ApiKeyCreated>("/admin/api-keys", payload);
    return res.data;
  },

  async update(id: string, payload: ApiKeyUpdate): Promise<ApiKeySummary> {
    const res = await api.patch<ApiKeySummary>(`/admin/api-keys/${id}`, payload);
    return res.data;
  },

  async revoke(id: string): Promise<void> {
    await api.delete(`/admin/api-keys/${id}`);
  },
};
