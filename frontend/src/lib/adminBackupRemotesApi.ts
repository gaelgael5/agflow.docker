import { api } from "./api";

export interface GDriveOAuthStartPayload {
  name: string;
  folder_name: string;
  client_id: string;
  client_secret: string;
}

export interface GDriveOAuthStartResponse {
  state: string;
  authorize_url: string;
}

export interface GDriveOAuthSessionInfo {
  status: "pending" | "completed" | "failed";
  connection_id: string | null;
  user_email: string | null;
  folder_id: string | null;
}

export const adminBackupRemotesApi = {
  async fetchGDriveRedirectUri(): Promise<{ redirect_uri: string }> {
    const r = await api.get<{ redirect_uri: string }>(
      "/admin/backup-remotes/oauth/gdrive/redirect-uri",
    );
    return r.data;
  },

  async startGDriveOAuth(payload: GDriveOAuthStartPayload): Promise<GDriveOAuthStartResponse> {
    const r = await api.post<GDriveOAuthStartResponse>(
      "/admin/backup-remotes/oauth/gdrive/start",
      payload,
    );
    return r.data;
  },

  async fetchGDriveOAuthSession(state: string): Promise<GDriveOAuthSessionInfo> {
    const r = await api.get<GDriveOAuthSessionInfo>(
      `/admin/backup-remotes/oauth/gdrive/session/${state}`,
    );
    return r.data;
  },

  async reauthorizeConnection(id: string): Promise<GDriveOAuthStartResponse> {
    const r = await api.post<GDriveOAuthStartResponse>(
      `/admin/backup-remotes/${id}/reauthorize`,
    );
    return r.data;
  },
};
