import { api } from "./api";

export interface VaultStatus {
  initialized: boolean;
  salt: string | null;
  test_ciphertext: string | null;
  test_iv: string | null;
}

export interface VaultSetup {
  salt: string;
  test_ciphertext: string;
  test_iv: string;
}

export interface UserSecretSummary {
  id: string;
  user_id: string;
  name: string;
  ciphertext: string;
  iv: string;
  created_at: string;
  updated_at: string;
}

export interface UserSecretCreate {
  name: string;
  ciphertext: string;
  iv: string;
}

export interface UserSecretUpdate {
  ciphertext: string;
  iv: string;
}

export const vaultApi = {
  async getStatus(): Promise<VaultStatus> {
    const res = await api.get<VaultStatus>("/admin/vault/status");
    return res.data;
  },
  async setup(payload: VaultSetup): Promise<void> {
    await api.post("/admin/vault/setup", payload);
  },
};

export const userSecretsApi = {
  async list(): Promise<UserSecretSummary[]> {
    const res = await api.get<UserSecretSummary[]>("/admin/user-secrets");
    return res.data;
  },
  async create(payload: UserSecretCreate): Promise<UserSecretSummary> {
    const res = await api.post<UserSecretSummary>("/admin/user-secrets", payload);
    return res.data;
  },
  async update(id: string, payload: UserSecretUpdate): Promise<UserSecretSummary> {
    const res = await api.put<UserSecretSummary>(`/admin/user-secrets/${id}`, payload);
    return res.data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/user-secrets/${id}`);
  },
};
