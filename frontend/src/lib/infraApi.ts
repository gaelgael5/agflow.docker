import { api } from "./api";

// ── Categories ────────────────────────────────────────

export interface InfraCategory {
  name: string;
  is_vps: boolean;
}

export interface InfraCategoryAction {
  id: string;
  name: string;
  is_required: boolean;
}

export const infraCategoriesApi = {
  async list(): Promise<InfraCategory[]> {
    return (await api.get<InfraCategory[]>("/infra/categories")).data;
  },
  async create(name: string, isVps = false): Promise<InfraCategory> {
    return (await api.post<InfraCategory>("/infra/categories", { name, is_vps: isVps })).data;
  },
  async setVps(name: string, isVps: boolean): Promise<InfraCategory> {
    return (await api.patch<InfraCategory>(
      `/infra/categories/${encodeURIComponent(name)}`,
      { is_vps: isVps },
    )).data;
  },
  async remove(name: string): Promise<void> {
    await api.delete(`/infra/categories/${encodeURIComponent(name)}`);
  },
  async listActions(category: string): Promise<InfraCategoryAction[]> {
    return (await api.get<InfraCategoryAction[]>(
      `/infra/categories/${encodeURIComponent(category)}/actions`,
    )).data;
  },
  async createAction(category: string, name: string, isRequired = false): Promise<InfraCategoryAction> {
    return (await api.post<InfraCategoryAction>(
      `/infra/categories/${encodeURIComponent(category)}/actions`,
      { name, is_required: isRequired },
    )).data;
  },
  async setActionRequired(category: string, name: string, isRequired: boolean): Promise<InfraCategoryAction> {
    return (await api.patch<InfraCategoryAction>(
      `/infra/categories/${encodeURIComponent(category)}/actions/${encodeURIComponent(name)}`,
      { is_required: isRequired },
    )).data;
  },
  async removeAction(category: string, name: string): Promise<void> {
    await api.delete(
      `/infra/categories/${encodeURIComponent(category)}/actions/${encodeURIComponent(name)}`,
    );
  },
};

// ── Named Types (variantes : Proxmox/SSH, LXC/SSH) ────

export interface InfraNamedType {
  id: string;
  name: string;
  // type_id is the category name (FK → infra_categories.name)
  type_id: string;
  type_name: string;
  // sub_type_id is a named_type UUID (self-reference)
  sub_type_id: string | null;
  sub_type_name: string | null;
  connection_type: string;
  created_at: string;
  updated_at: string;
}

export interface InfraNamedTypeCreatePayload {
  name: string;
  type_id: string;
  sub_type_id?: string | null;
  connection_type: string;
}

export interface InfraNamedTypeUpdatePayload {
  name?: string;
  type_id?: string;
  sub_type_id?: string | null;
  connection_type?: string;
}

export const infraNamedTypesApi = {
  async list(): Promise<InfraNamedType[]> {
    return (await api.get<InfraNamedType[]>("/infra/named-types")).data;
  },
  async get(id: string): Promise<InfraNamedType> {
    return (await api.get<InfraNamedType>(`/infra/named-types/${id}`)).data;
  },
  async create(p: InfraNamedTypeCreatePayload): Promise<InfraNamedType> {
    return (await api.post<InfraNamedType>("/infra/named-types", p)).data;
  },
  async update(id: string, p: InfraNamedTypeUpdatePayload): Promise<InfraNamedType> {
    return (await api.put<InfraNamedType>(`/infra/named-types/${id}`, p)).data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/infra/named-types/${id}`);
  },
};

// ── Named Type Actions (URL par action × named_type) ──

export interface InfraNamedTypeAction {
  id: string;
  named_type_id: string;
  category_action_id: string;
  action_name: string;
  url: string;
  created_at: string;
  updated_at: string;
}

export const infraNamedTypeActionsApi = {
  async list(namedTypeId: string): Promise<InfraNamedTypeAction[]> {
    return (await api.get<InfraNamedTypeAction[]>(
      `/infra/named-types/${namedTypeId}/actions`,
    )).data;
  },
  async create(
    namedTypeId: string,
    categoryActionId: string,
    url: string,
  ): Promise<InfraNamedTypeAction> {
    return (await api.post<InfraNamedTypeAction>(
      `/infra/named-types/${namedTypeId}/actions`,
      { category_action_id: categoryActionId, url },
    )).data;
  },
  async update(
    namedTypeId: string,
    actionId: string,
    url: string,
  ): Promise<InfraNamedTypeAction> {
    return (await api.put<InfraNamedTypeAction>(
      `/infra/named-types/${namedTypeId}/actions/${actionId}`,
      { url },
    )).data;
  },
  async remove(namedTypeId: string, actionId: string): Promise<void> {
    await api.delete(`/infra/named-types/${namedTypeId}/actions/${actionId}`);
  },
};

// ── Machines (fusion des ex-servers + ex-machines) ────

export interface RequiredActionStatus {
  name: string;
  done: boolean;
}

export interface MachineSummary {
  id: string;
  name: string;
  type_id: string;
  type_name: string;
  category: string;
  host: string;
  port: number;
  username: string | null;
  has_password: boolean;
  certificate_id: string | null;
  parent_id: string | null;
  user_id: string | null;
  environment: string | null;
  children_count: number;
  metadata: Record<string, string>;
  status: string;
  required_actions: RequiredActionStatus[];
  created_at: string;
  updated_at: string;
}

export interface MachineCreatePayload {
  name?: string;
  type_id: string;
  host: string;
  port?: number;
  username?: string;
  password?: string;
  certificate_id?: string;
  parent_id?: string;
  user_id?: string;
  environment?: string;
}

export interface MachineUpdatePayload {
  name?: string;
  host?: string;
  port?: number;
  username?: string;
  password?: string;
  certificate_id?: string;
  user_id?: string | null;
  environment?: string | null;
}

export interface DockerContainer {
  id: string;
  name: string;
  image: string;
  status: string;
  state: string;
  ports: string;
}

export interface ScriptManifestArg {
  arg: string;
  label_fr: string;
  description_fr: string;
  type: "string" | "integer" | "boolean" | "select";
  required: boolean;
  default?: string | number | boolean;
  pattern?: string;
  min?: number;
  max?: number;
  options?: { value: string; label: string }[];
}

export interface ScriptManifest {
  args: ScriptManifestArg[];
  command: string;
}

export interface ScriptRunResult {
  exit_code: number;
  stdout: string;
  stderr: string;
  command: string;
}

export interface MachineRun {
  id: string;
  machine_id: string;
  action_id: string;
  action_name: string;
  started_at: string;
  finished_at: string | null;
  success: boolean | null;
  exit_code: number | null;
  error_message: string | null;
}

export const infraMachinesApi = {
  async list(): Promise<MachineSummary[]> {
    return (await api.get<MachineSummary[]>("/infra/machines")).data;
  },
  async create(p: MachineCreatePayload): Promise<MachineSummary> {
    return (await api.post<MachineSummary>("/infra/machines", p)).data;
  },
  async update(id: string, p: MachineUpdatePayload): Promise<MachineSummary> {
    return (await api.put<MachineSummary>(`/infra/machines/${id}`, p)).data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/infra/machines/${id}`);
  },
  async listContainers(id: string): Promise<{ containers: DockerContainer[]; machine_id: string }> {
    return (await api.get(`/infra/machines/${id}/containers`)).data;
  },
  async healthCheck(id: string): Promise<{ healthy: boolean; state: string; machine_id: string }> {
    return (await api.get(`/infra/machines/${id}/health`)).data;
  },
  async testConnection(id: string): Promise<{ success: boolean; message: string }> {
    return (await api.post(`/infra/machines/${id}/test-connection`)).data;
  },
  async runScript(id: string, scriptUrl: string, args: Record<string, string>): Promise<ScriptRunResult> {
    return (await api.post<ScriptRunResult>(
      `/infra/machines/${id}/run-script`,
      { script_url: scriptUrl, args },
    )).data;
  },
  async fetchManifest(url: string): Promise<ScriptManifest> {
    return (await api.get<ScriptManifest>(`/infra/machines/manifest`, { params: { url } })).data;
  },
  async listRuns(id: string, limit = 50): Promise<MachineRun[]> {
    return (await api.get<MachineRun[]>(`/infra/machines/${id}/runs`, { params: { limit } })).data;
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
  async rename(id: string, name: string): Promise<CertificateSummary> {
    return (await api.put<CertificateSummary>(`/infra/certificates/${id}`, { name })).data;
  },
  async getPublicKey(id: string): Promise<string> {
    return (await api.get<string>(`/infra/certificates/${id}/public-key`)).data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/infra/certificates/${id}`);
  },
};
