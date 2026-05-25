import { api } from "./api";

export interface NamedTypeEnvVar {
  id: string;
  named_type_id: string;
  name: string;
  description: string;
  position: number;
  is_secret: boolean;
  created_at: string;
  updated_at: string;
}

export interface NamedTypeEnvVarCreate {
  name: string;
  description?: string;
  position?: number;
  is_secret?: boolean;
}

export interface NamedTypeEnvVarUpdate {
  name?: string;
  description?: string;
  position?: number;
  is_secret?: boolean;
}

export interface MachineEnvVar {
  id: string;
  machine_id: string;
  named_type_env_var_id: string;
  name: string;
  description: string;
  value: string;
  is_secret: boolean;
  created_at: string;
  updated_at: string;
}

export interface MachineSecretEntry {
  vault_name: string;
  value: string;
}

export interface MachineEnvVarUpsert {
  values: Record<string, string>;
  secrets?: Record<string, MachineSecretEntry>;
}

export type EnvVarsMissingKind =
  | "value_empty"
  | "var_not_in_env"
  | "platform_secret_missing"
  | "machine_not_found"
  | "env_machine_var_not_found"
  | "unknown_ref";

export interface ProjectEnvVarsCheckMissingReason {
  var_name: string;
  kind: EnvVarsMissingKind;
  ref: string;
  detail: string;
}

export interface ProjectEnvVarsCheckMissing {
  group_script_id: string;
  script_id: string;
  script_name: string;
  group_id: string;
  group_name: string;
  machine_id: string | null;
  machine_name: string | null;
  target_kind: string;
  missing: ProjectEnvVarsCheckMissingReason[];
}

export interface ProjectEnvVarsCheck {
  project_id: string;
  total_missing: number;
  items: ProjectEnvVarsCheckMissing[];
}

export const namedTypeEnvVarsApi = {
  async list(namedTypeId: string): Promise<NamedTypeEnvVar[]> {
    return (await api.get<NamedTypeEnvVar[]>(`/infra/named-types/${namedTypeId}/env-vars`)).data;
  },
  async create(namedTypeId: string, payload: NamedTypeEnvVarCreate): Promise<NamedTypeEnvVar> {
    return (await api.post<NamedTypeEnvVar>(`/infra/named-types/${namedTypeId}/env-vars`, payload)).data;
  },
  async update(
    namedTypeId: string,
    envVarId: string,
    payload: NamedTypeEnvVarUpdate,
  ): Promise<NamedTypeEnvVar> {
    return (await api.put<NamedTypeEnvVar>(
      `/infra/named-types/${namedTypeId}/env-vars/${envVarId}`,
      payload,
    )).data;
  },
  async remove(namedTypeId: string, envVarId: string): Promise<void> {
    await api.delete(`/infra/named-types/${namedTypeId}/env-vars/${envVarId}`);
  },
};

export const machineEnvVarsApi = {
  async list(machineId: string): Promise<MachineEnvVar[]> {
    return (await api.get<MachineEnvVar[]>(`/infra/machines/${machineId}/env-vars`)).data;
  },
  async upsert(machineId: string, payload: MachineEnvVarUpsert): Promise<MachineEnvVar[]> {
    return (await api.put<MachineEnvVar[]>(`/infra/machines/${machineId}/env-vars`, payload))
      .data;
  },
};

export const projectEnvVarsApi = {
  async check(projectId: string): Promise<ProjectEnvVarsCheck> {
    return (await api.get<ProjectEnvVarsCheck>(`/admin/projects/${projectId}/env-vars-check`))
      .data;
  },
};
