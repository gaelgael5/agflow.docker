import { api } from "@/lib/api";

export interface TemplateSummary {
  slug: string;
  display_name: string;
  description: string;
  cultures: string[];
}

export interface TemplateFileInfo {
  filename: string;
  culture: string;
  size: number;
}

export interface TemplateDetail {
  slug: string;
  display_name: string;
  description: string;
  files: TemplateFileInfo[];
}

export const templatesApi = {
  async list(): Promise<TemplateSummary[]> {
    const res = await api.get<TemplateSummary[]>("/admin/templates");
    return res.data;
  },
  async get(slug: string): Promise<TemplateDetail> {
    const res = await api.get<TemplateDetail>(`/admin/templates/${slug}`);
    return res.data;
  },
  async create(payload: { slug: string; display_name: string; description?: string }): Promise<TemplateSummary> {
    const res = await api.post<TemplateSummary>("/admin/templates", payload);
    return res.data;
  },
  async update(slug: string, payload: { display_name?: string; description?: string }): Promise<TemplateSummary> {
    const res = await api.put<TemplateSummary>(`/admin/templates/${slug}`, payload);
    return res.data;
  },
  async remove(slug: string): Promise<void> {
    await api.delete(`/admin/templates/${slug}`);
  },
  async getFile(slug: string, filename: string): Promise<{ filename: string; content: string }> {
    const res = await api.get<{ filename: string; content: string }>(`/admin/templates/${slug}/files/${filename}`);
    return res.data;
  },
  async createFile(slug: string, filename: string, content: string): Promise<void> {
    await api.post(`/admin/templates/${slug}/files`, { filename, content });
  },
  async updateFile(slug: string, filename: string, content: string): Promise<void> {
    await api.put(`/admin/templates/${slug}/files/${filename}`, { content });
  },
  async deleteFile(slug: string, filename: string): Promise<void> {
    await api.delete(`/admin/templates/${slug}/files/${filename}`);
  },
};
