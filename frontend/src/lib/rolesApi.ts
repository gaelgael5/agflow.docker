import { api } from "./api";

export type Section = string;
export const NATIVE_SECTIONS: readonly string[] = [
  "roles",
  "missions",
  "competences",
] as const;

export interface RoleSummary {
  id: string;
  display_name: string;
  description: string;
  service_types: string[];
  identity_md: string;
  prompt_orchestrator_md: string;
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

export interface SectionSummary {
  name: string;
  display_name: string;
  is_native: boolean;
  position: number;
}

export interface SectionWithDocuments extends SectionSummary {
  documents: DocumentSummary[];
}

export interface SectionCreate {
  name: string;
  display_name: string;
}

export interface RoleDetail {
  role: RoleSummary;
  sections: SectionWithDocuments[];
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
  name?: string;
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
  async listSections(roleId: string): Promise<SectionSummary[]> {
    const res = await api.get<SectionSummary[]>(
      `/admin/roles/${roleId}/sections`,
    );
    return res.data;
  },
  async createSection(
    roleId: string,
    payload: SectionCreate,
  ): Promise<SectionSummary> {
    const res = await api.post<SectionSummary>(
      `/admin/roles/${roleId}/sections`,
      payload,
    );
    return res.data;
  },
  async deleteSection(roleId: string, name: string): Promise<void> {
    await api.delete(`/admin/roles/${roleId}/sections/${name}`);
  },
  async exportZip(roleId: string): Promise<Blob> {
    const res = await api.get(`/admin/roles/${roleId}/export`, {
      responseType: "blob",
    });
    return res.data as Blob;
  },
  async importZip(roleId: string, file: File): Promise<RoleDetail> {
    const form = new FormData();
    form.append("file", file);
    const res = await api.post<RoleDetail>(
      `/admin/roles/${roleId}/import`,
      form,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    return res.data;
  },
};
