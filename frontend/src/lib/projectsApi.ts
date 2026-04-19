import { api } from "./api";

export interface ProjectSummary {
  id: string;
  display_name: string;
  description: string;
  environment: "dev" | "staging" | "prod";
  tags: string[];
}

export interface ProjectCreatePayload {
  id: string;
  display_name: string;
  description?: string;
  environment?: "dev" | "staging" | "prod";
  tags?: string[];
}

export interface ProjectUpdatePayload {
  display_name?: string;
  description?: string;
  environment?: "dev" | "staging" | "prod";
  tags?: string[];
}

export const projectsApi = {
  async list(): Promise<ProjectSummary[]> {
    return (await api.get<ProjectSummary[]>("/admin/projects")).data;
  },
  async get(id: string): Promise<ProjectSummary> {
    return (await api.get<ProjectSummary>(`/admin/projects/${id}`)).data;
  },
  async create(p: ProjectCreatePayload): Promise<ProjectSummary> {
    return (await api.post<ProjectSummary>("/admin/projects", p)).data;
  },
  async update(id: string, p: ProjectUpdatePayload): Promise<ProjectSummary> {
    return (await api.put<ProjectSummary>(`/admin/projects/${id}`, p)).data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/projects/${id}`);
  },
};
