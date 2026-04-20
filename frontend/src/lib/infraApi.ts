import { api } from "./api";

// ── Types ─────────────────────────────────────────────

export interface InfraType {
  name: string;
  type: "platform" | "service";
}

export const infraTypesApi = {
  async list(type?: "platform" | "service"): Promise<InfraType[]> {
    const params = type ? `?type=${type}` : "";
    return (await api.get<InfraType[]>(`/infra/types${params}`)).data;
  },
  async create(name: string, type: "platform" | "service"): Promise<InfraType> {
    return (await api.post<InfraType>("/infra/types", { name, type })).data;
  },
  async remove(name: string): Promise<void> {
    await api.delete(`/infra/types/${name}`);
  },
  async reload(): Promise<{ status: string; platforms: number; services: number }> {
    return (await api.post("/infra/types/reload")).data;
  },
};

// ── Platforms ─────────────────────────────────────────

export interface PlatformDef {
  name: string;
  type: string;
  service: string;
  connection: string;
  scripts: Record<string, string[]>;
}

export interface PlatformCreatePayload {
  name: string;
  type?: string;
  service: string;
  connection?: string;
  scripts?: Record<string, string[]>;
}

export const infraPlatformsApi = {
  async list(): Promise<PlatformDef[]> {
    return (await api.get<PlatformDef[]>("/infra/platforms")).data;
  },
  async get(name: string): Promise<PlatformDef> {
    return (await api.get<PlatformDef>(`/infra/platforms/${name}`)).data;
  },
  async create(p: PlatformCreatePayload): Promise<PlatformDef> {
    return (await api.post<PlatformDef>("/infra/platforms", p)).data;
  },
  async update(name: string, p: PlatformCreatePayload): Promise<PlatformDef> {
    return (await api.put<PlatformDef>(`/infra/platforms/${encodeURIComponent(name)}`, p)).data;
  },
  async remove(name: string): Promise<void> {
    await api.delete(`/infra/platforms/${encodeURIComponent(name)}`);
  },
};

// ── Services ─────────────────────────────────────────

export interface ServiceDef {
  name: string;
  type: string;
  connection: string;
  scripts: string[];
}

export interface ServiceCreatePayload {
  name: string;
  type?: string;
  connection?: string;
  scripts?: string[];
}

export const infraServicesApi = {
  async list(): Promise<ServiceDef[]> {
    return (await api.get<ServiceDef[]>("/infra/services")).data;
  },
  async get(name: string): Promise<ServiceDef> {
    return (await api.get<ServiceDef>(`/infra/services/${name}`)).data;
  },
  async create(p: ServiceCreatePayload): Promise<ServiceDef> {
    return (await api.post<ServiceDef>("/infra/services", p)).data;
  },
  async update(name: string, p: ServiceCreatePayload): Promise<ServiceDef> {
    return (await api.put<ServiceDef>(`/infra/services/${encodeURIComponent(name)}`, p)).data;
  },
  async remove(name: string): Promise<void> {
    await api.delete(`/infra/services/${encodeURIComponent(name)}`);
  },
};

// ── Servers ──────────────────────────────────────────

export interface ServerSummary {
  id: string;
  name: string;
  type: string;
  host: string;
  port: number;
  username: string | null;
  has_password: boolean;
  certificate_id: string | null;
  machine_count: number;
  metadata: Record<string, string>;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ServerCreatePayload {
  name?: string;
  type: string;
  host: string;
  port?: number;
  username?: string;
  password?: string;
  certificate_id?: string;
}

export interface ScriptManifest {
  args: { arg: string; label_fr: string; description_fr: string; type: string; required: boolean }[];
  command: string;
}

export interface ScriptRunResult {
  exit_code: number;
  stdout: string;
  stderr: string;
  command: string;
}

export const infraServersApi = {
  async list(): Promise<ServerSummary[]> {
    return (await api.get<ServerSummary[]>("/infra/servers")).data;
  },
  async create(p: ServerCreatePayload): Promise<ServerSummary> {
    return (await api.post<ServerSummary>("/infra/servers", p)).data;
  },
  async update(id: string, p: ServerCreatePayload): Promise<ServerSummary> {
    return (await api.put<ServerSummary>(`/infra/servers/${id}`, p)).data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/infra/servers/${id}`);
  },
  async healthCheck(id: string): Promise<{ healthy: boolean; state: string; server_id: string }> {
    return (await api.get(`/infra/servers/${id}/health`)).data;
  },
  async testConnection(id: string): Promise<{ success: boolean; message: string }> {
    return (await api.post(`/infra/servers/${id}/test-connection`)).data;
  },
  async runScript(id: string, scriptUrl: string, args: Record<string, string>): Promise<ScriptRunResult> {
    return (await api.post<ScriptRunResult>(`/infra/servers/${id}/run-script`, { script_url: scriptUrl, args })).data;
  },
  async fetchManifest(url: string): Promise<ScriptManifest> {
    return (await api.get<ScriptManifest>(`/infra/servers/manifest`, { params: { url } })).data;
  },
};

// ── Certificates ──────────────────────────────────────

export interface CertificateSummary {
  id: string;
  name: string;
  key_type: string;
  has_private_key: boolean;
  has_public_key: boolean;
  has_passphrase: boolean;
  created_at: string;
  updated_at: string;
}

export interface CertificateCreatePayload {
  name: string;
  private_key: string;
  public_key?: string;
  passphrase?: string;
}

export interface CertificateGeneratePayload {
  name: string;
  key_type: "rsa" | "ed25519";
  passphrase?: string;
}

export interface CertificateGenerateResult {
  certificate: CertificateSummary;
  public_key: string;
}

export const infraCertificatesApi = {
  async list(): Promise<CertificateSummary[]> {
    return (await api.get<CertificateSummary[]>("/infra/certificates")).data;
  },
  async create(p: CertificateCreatePayload): Promise<CertificateSummary> {
    return (await api.post<CertificateSummary>("/infra/certificates", p)).data;
  },
  async generate(p: CertificateGeneratePayload): Promise<CertificateGenerateResult> {
    return (await api.post<CertificateGenerateResult>("/infra/certificates/generate", p)).data;
  },
  async getPublicKey(id: string): Promise<string> {
    return (await api.get<string>(`/infra/certificates/${id}/public-key`)).data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/infra/certificates/${id}`);
  },
};
