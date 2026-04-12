import { api } from "./api";

export interface UserSummary {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  role: string;
  scopes: string[];
  status: "pending" | "approved" | "disabled";
  created_at: string;
  approved_at: string | null;
  last_login: string | null;
  api_key_count: number;
}

export interface UserCreate {
  email: string;
  name?: string;
  role?: string;
  scopes?: string[];
  status?: "pending" | "approved" | "disabled";
}

export interface UserUpdate {
  name?: string;
  role?: string;
  scopes?: string[];
}

export const usersApi = {
  async list(): Promise<UserSummary[]> {
    const res = await api.get<UserSummary[]>("/admin/users");
    return res.data;
  },

  async get(id: string): Promise<UserSummary> {
    const res = await api.get<UserSummary>(`/admin/users/${id}`);
    return res.data;
  },

  async create(payload: UserCreate): Promise<UserSummary> {
    const res = await api.post<UserSummary>("/admin/users", payload);
    return res.data;
  },

  async update(id: string, payload: UserUpdate): Promise<UserSummary> {
    const res = await api.patch<UserSummary>(`/admin/users/${id}`, payload);
    return res.data;
  },

  async approve(id: string): Promise<UserSummary> {
    const res = await api.post<UserSummary>(`/admin/users/${id}/approve`);
    return res.data;
  },

  async disable(id: string): Promise<UserSummary> {
    const res = await api.post<UserSummary>(`/admin/users/${id}/disable`);
    return res.data;
  },

  async enable(id: string): Promise<UserSummary> {
    const res = await api.post<UserSummary>(`/admin/users/${id}/enable`);
    return res.data;
  },

  async remove(id: string): Promise<void> {
    await api.delete(`/admin/users/${id}`);
  },
};
