import { api } from "./api";

export type Scope = "global" | "agent";

export interface SecretSummary {
  id: string;
  var_name: string;
  scope: Scope;
  created_at: string;
  updated_at: string;
  used_by: string[];
}

export interface SecretReveal {
  id: string;
  var_name: string;
  value: string;
}

export interface SecretTestResult {
  supported: boolean;
  ok: boolean;
  detail: string;
}

export interface SecretCreate {
  var_name: string;
  value: string;
  scope?: Scope;
}

export interface SecretUpdate {
  value?: string;
  scope?: Scope;
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
  async update(id: string, payload: SecretUpdate): Promise<SecretSummary> {
    const res = await api.put<SecretSummary>(`/admin/secrets/${id}`, payload);
    return res.data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/secrets/${id}`);
  },
  async reveal(id: string): Promise<SecretReveal> {
    const res = await api.get<SecretReveal>(`/admin/secrets/${id}/reveal`);
    return res.data;
  },
  async test(id: string): Promise<SecretTestResult> {
    const res = await api.post<SecretTestResult>(`/admin/secrets/${id}/test`);
    return res.data;
  },
};
