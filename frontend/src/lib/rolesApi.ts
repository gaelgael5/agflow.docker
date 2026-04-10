import { api } from "./api";

export type Section = "roles" | "missions" | "competences";

export interface RoleSummary {
  id: string;
  display_name: string;
  description: string;
  service_types: string[];
  identity_md: string;
  prompt_orchestrator_md: string;
  runtime_config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DocumentSummary {
  id: string;
  role_id: string;
  section: Section;
  parent_path: string;
  name: string;
  content_md: string;
  protected: boolean;
  created_at: string;
  updated_at: string;
}

export interface RoleDetail {
  role: RoleSummary;
  roles_documents: DocumentSummary[];
  missions_documents: DocumentSummary[];
  competences_documents: DocumentSummary[];
}

export interface RoleCreate {
  id: string;
  display_name: string;
  description?: string;
  service_types?: string[];
  identity_md?: string;
}

export interface RoleUpdate {
  display_name?: string;
  description?: string;
  service_types?: string[];
  identity_md?: string;
}

export interface DocumentCreate {
  section: Section;
  name: string;
  content_md?: string;
  protected?: boolean;
}

export interface DocumentUpdate {
  content_md?: string;
  protected?: boolean;
}

export const rolesApi = {
  async list(): Promise<RoleSummary[]> {
    const res = await api.get<RoleSummary[]>("/admin/roles");
    return res.data;
  },
  async get(id: string): Promise<RoleDetail> {
    const res = await api.get<RoleDetail>(`/admin/roles/${id}`);
    return res.data;
  },
  async create(payload: RoleCreate): Promise<RoleSummary> {
    const res = await api.post<RoleSummary>("/admin/roles", payload);
    return res.data;
  },
  async update(id: string, payload: RoleUpdate): Promise<RoleSummary> {
    const res = await api.put<RoleSummary>(`/admin/roles/${id}`, payload);
    return res.data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/roles/${id}`);
  },
  async generatePrompts(id: string): Promise<RoleSummary> {
    const res = await api.post<RoleSummary>(`/admin/roles/${id}/generate-prompts`);
    return res.data;
  },
  async createDocument(
    roleId: string,
    payload: DocumentCreate,
  ): Promise<DocumentSummary> {
    const res = await api.post<DocumentSummary>(
      `/admin/roles/${roleId}/documents`,
      payload,
    );
    return res.data;
  },
  async updateDocument(
    roleId: string,
    docId: string,
    payload: DocumentUpdate,
  ): Promise<DocumentSummary> {
    const res = await api.put<DocumentSummary>(
      `/admin/roles/${roleId}/documents/${docId}`,
      payload,
    );
    return res.data;
  },
  async deleteDocument(roleId: string, docId: string): Promise<void> {
    await api.delete(`/admin/roles/${roleId}/documents/${docId}`);
  },
};
