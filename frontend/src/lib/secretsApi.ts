import { api } from "./api";

export type EnvVarStatus = "missing" | "empty" | "ok";
export type EnvVarStatusMap = Record<string, EnvVarStatus>;

export interface SecretSummary {
  name: string;
  is_placeholder: boolean;
  description: string | null;
  tags: string[];
}

export interface SecretReveal {
  name: string;
  value: string;
}

export interface SecretTestResult {
  supported: boolean;
  ok: boolean;
  detail: string;
}

export interface SecretCreate {
  name: string;
  value: string;
}

export interface SecretUpdate {
  value: string;
}

export const secretsApi = {
  async list(): Promise<SecretSummary[]> {
    const res = await api.get<SecretSummary[]>("/admin/secrets");
    return res.data;
  },
  async create(payload: SecretCreate): Promise<SecretSummary> {
    const res = await api.post<SecretSummary>("/admin/secrets", payload);
    return res.data;
  },
  async update(name: string, payload: SecretUpdate): Promise<SecretSummary> {
    const res = await api.put<SecretSummary>(`/admin/secrets/${name}`, payload);
    return res.data;
  },
  async remove(name: string): Promise<void> {
    await api.delete(`/admin/secrets/${name}`);
  },
  async reveal(name: string): Promise<SecretReveal> {
    const res = await api.get<SecretReveal>(`/admin/secrets/${name}/reveal`);
    return res.data;
  },
  async test(name: string): Promise<SecretTestResult> {
    const res = await api.post<SecretTestResult>(`/admin/secrets/${name}/test`);
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
