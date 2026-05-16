import { api } from "./api";

export interface HarpocrateVaultSummary {
  id: string;
  name: string;
  base_url: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateVaultPayload {
  name: string;
  base_url: string;
  api_key: string;
  is_default?: boolean;
}

export interface UpdateVaultPayload {
  name?: string;
  base_url?: string;
  api_key?: string;
  is_default?: boolean;
}

export interface TestConnectionResult {
  ok: boolean;
  error: string | null;
}

export const harpocrateVaultsApi = {
  async list(): Promise<HarpocrateVaultSummary[]> {
    const res = await api.get<HarpocrateVaultSummary[]>("/admin/harpocrate-vaults");
    return res.data;
  },

  async create(payload: CreateVaultPayload): Promise<HarpocrateVaultSummary> {
    const res = await api.post<HarpocrateVaultSummary>(
      "/admin/harpocrate-vaults",
      payload,
    );
    return res.data;
  },

  async update(id: string, payload: UpdateVaultPayload): Promise<HarpocrateVaultSummary> {
    const res = await api.put<HarpocrateVaultSummary>(
      `/admin/harpocrate-vaults/${id}`,
      payload,
    );
    return res.data;
  },

  async remove(id: string): Promise<void> {
    await api.delete(`/admin/harpocrate-vaults/${id}`);
  },

  async setDefault(id: string): Promise<HarpocrateVaultSummary> {
    const res = await api.post<HarpocrateVaultSummary>(
      `/admin/harpocrate-vaults/${id}/set-default`,
    );
    return res.data;
  },

  async testConnection(id: string): Promise<TestConnectionResult> {
    const res = await api.post<TestConnectionResult>(
      `/admin/harpocrate-vaults/${id}/test-connection`,
    );
    return res.data;
  },
};
