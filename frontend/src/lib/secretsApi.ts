import { api } from "./api";

export type EnvVarStatus = "missing" | "empty" | "ok";
export type EnvVarStatusMap = Record<string, EnvVarStatus>;

export type SecretType = "vault" | "env";

export interface PlatformSecretSummary {
  id: string;
  key: string;
  type: SecretType;
  name: string;
  has_value: boolean;
  created_at: string;
  updated_at: string;
}

export interface PlatformSecretReveal {
  id: string;
  name: string;
  value: string;
}

export interface CreateVaultPayload {
  name: string;
  value: string;
}

export interface CreateEnvPayload {
  name: string;
  value: string;
}

export interface UpdateSecretPayload {
  value: string;
}

export const secretsApi = {
  async list(): Promise<PlatformSecretSummary[]> {
    const res = await api.get<PlatformSecretSummary[]>("/admin/secrets");
    return res.data;
  },

  async createVault(payload: CreateVaultPayload): Promise<PlatformSecretSummary> {
    const res = await api.post<PlatformSecretSummary>("/admin/secrets/vault", payload);
    return res.data;
  },

  async createEnv(payload: CreateEnvPayload): Promise<PlatformSecretSummary> {
    const res = await api.post<PlatformSecretSummary>("/admin/secrets/env", payload);
    return res.data;
  },

  async update(id: string, payload: UpdateSecretPayload): Promise<void> {
    await api.put(`/admin/secrets/${id}`, payload);
  },

  async remove(id: string): Promise<void> {
    await api.delete(`/admin/secrets/${id}`);
  },

  async reveal(id: string): Promise<PlatformSecretReveal> {
    const res = await api.get<PlatformSecretReveal>(`/admin/secrets/${id}/reveal`);
    return res.data;
  },

  async resolveStatus(varNames: string[]): Promise<EnvVarStatusMap> {
    if (varNames.length === 0) return {};
    const res = await api.get<EnvVarStatusMap>("/admin/secrets/resolve-status", {
      params: { var_names: varNames.join(",") },
    });
    return res.data;
  },
};
