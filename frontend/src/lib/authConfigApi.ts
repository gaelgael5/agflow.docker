import { api } from "./api";

export type AuthMode = "local" | "keycloak";

export interface AuthConfig {
  mode: AuthMode;
  keycloak_url: string;
  keycloak_realm: string;
  keycloak_client_id: string;
  has_secret: boolean;
  vault_name: string;
  updated_at: string;
  updated_by_user_id: string | null;
}

export interface AuthConfigUpdate {
  mode?: AuthMode;
  keycloak_url?: string;
  keycloak_realm?: string;
  keycloak_client_id?: string;
  keycloak_client_secret?: string;
  vault_name?: string;
}

export interface AuthTestRequest {
  keycloak_url: string;
  keycloak_realm: string;
  keycloak_client_id: string;
  keycloak_client_secret?: string;
  vault_name?: string;
}

export interface AuthTestResult {
  ok: boolean;
  step: "discovery" | "token" | "done";
  detail: string;
  discovery_ok: boolean;
  token_ok: boolean;
}

export const authConfigApi = {
  getConfig: async (): Promise<AuthConfig> =>
    (await api.get<AuthConfig>("/admin/auth-config")).data,
  updateConfig: async (payload: AuthConfigUpdate): Promise<AuthConfig> =>
    (await api.put<AuthConfig>("/admin/auth-config", payload)).data,
  testConnection: async (payload: AuthTestRequest): Promise<AuthTestResult> =>
    (await api.post<AuthTestResult>("/admin/auth-config/test", payload)).data,
};
