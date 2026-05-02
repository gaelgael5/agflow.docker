import { api } from "./api";

export interface AppEntry {
  key: string;
  label: string;
  icon: string;
  url: string;
}

export interface AppsResponse {
  urls: AppEntry[];
}

export const appsApi = {
  async list(): Promise<AppsResponse> {
    const res = await api.get<AppsResponse>("/admin/apps");
    return res.data;
  },
};
