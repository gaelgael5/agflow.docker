import { api } from "./api";

export interface UserSecretSummary {
  name: string;
  description?: string | null;
}

export interface UserSecretReveal {
  name: string;
  value: string;
}

export const userSecretsApi = {
  list: () => api.get<UserSecretSummary[]>("/admin/user-secrets").then(r => r.data),
  create: (payload: { name: string; value: string; description?: string }) =>
    api.post<UserSecretSummary>("/admin/user-secrets", payload).then(r => r.data),
  reveal: (name: string) =>
    api.get<UserSecretReveal>(`/admin/user-secrets/${name}/reveal`).then(r => r.data),
  update: (name: string, value: string) =>
    api.put<UserSecretSummary>(`/admin/user-secrets/${name}`, { value }).then(r => r.data),
  remove: (name: string) =>
    api.delete(`/admin/user-secrets/${name}`),
};
