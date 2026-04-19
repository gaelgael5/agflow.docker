import { api } from "./api";

export interface ThemeSummary {
  slug: string;
  display_name: string;
  description: string;
  provider: string;
  character_count: number;
  image_count: number;
}

export interface ThemeDetail extends ThemeSummary {
  prompt: string;
  size: string;
  quality: string;
  style: string;
  characters: CharacterSummary[];
}

export interface CharacterSummary {
  slug: string;
  display_name: string;
  description: string;
  image_count: number;
  selected: number | null;
}

export interface CharacterDetail extends CharacterSummary {
  prompt: string;
  images: ImageInfo[];
}

export interface ImageInfo {
  number: number;
  filename: string;
  size_bytes: number;
  is_selected: boolean;
}

export interface ThemeCreatePayload {
  slug: string;
  display_name: string;
  description?: string;
  prompt: string;
  provider?: string;
  size?: string;
  quality?: string;
  style?: string;
}

export interface ThemeUpdatePayload {
  display_name?: string;
  description?: string;
  prompt?: string;
  provider?: string;
  size?: string;
  quality?: string;
  style?: string;
}

export interface CharacterCreatePayload {
  slug: string;
  display_name: string;
  description?: string;
  prompt: string;
}

export interface CharacterUpdatePayload {
  display_name?: string;
  description?: string;
  prompt?: string;
}

export const avatarsApi = {
  // Themes
  async listThemes(): Promise<ThemeSummary[]> {
    return (await api.get<ThemeSummary[]>("/admin/avatars")).data;
  },
  async getTheme(slug: string): Promise<ThemeDetail> {
    return (await api.get<ThemeDetail>(`/admin/avatars/${slug}`)).data;
  },
  async createTheme(p: ThemeCreatePayload): Promise<ThemeSummary> {
    return (await api.post<ThemeSummary>("/admin/avatars", p)).data;
  },
  async updateTheme(slug: string, p: ThemeUpdatePayload): Promise<ThemeDetail> {
    return (await api.put<ThemeDetail>(`/admin/avatars/${slug}`, p)).data;
  },
  async deleteTheme(slug: string): Promise<void> {
    await api.delete(`/admin/avatars/${slug}`);
  },

  // Characters
  async getCharacter(theme: string, char: string): Promise<CharacterDetail> {
    return (await api.get<CharacterDetail>(`/admin/avatars/${theme}/characters/${char}`)).data;
  },
  async createCharacter(theme: string, p: CharacterCreatePayload): Promise<CharacterSummary> {
    return (await api.post<CharacterSummary>(`/admin/avatars/${theme}/characters`, p)).data;
  },
  async updateCharacter(theme: string, char: string, p: CharacterUpdatePayload): Promise<CharacterDetail> {
    return (await api.put<CharacterDetail>(`/admin/avatars/${theme}/characters/${char}`, p)).data;
  },
  async deleteCharacter(theme: string, char: string): Promise<void> {
    await api.delete(`/admin/avatars/${theme}/characters/${char}`);
  },

  // Images
  async generateImage(theme: string, char: string, apiKey?: string): Promise<{ number: number; size_bytes: number }> {
    return (await api.post(`/admin/avatars/${theme}/characters/${char}/generate`, apiKey ? { api_key: apiKey } : {})).data;
  },
  async uploadImage(theme: string, char: string, file: File): Promise<{ number: number; size_bytes: number }> {
    const form = new FormData();
    form.append("file", file);
    return (await api.post(`/admin/avatars/${theme}/characters/${char}/upload`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    })).data;
  },
  async deleteImage(theme: string, char: string, n: number): Promise<void> {
    await api.delete(`/admin/avatars/${theme}/characters/${char}/images/${n}`);
  },
  async selectImage(theme: string, char: string, n: number): Promise<void> {
    await api.post(`/admin/avatars/${theme}/characters/${char}/select/${n}`);
  },

  imageUrl(theme: string, char: string, n: number): string {
    return `/api/admin/avatars/${theme}/characters/${char}/images/${n}`;
  },

  async fetchImageBlob(theme: string, char: string, n: number): Promise<string> {
    const res = await api.get(`/admin/avatars/${theme}/characters/${char}/images/${n}`, {
      responseType: "blob",
    });
    return URL.createObjectURL(res.data as Blob);
  },
};
