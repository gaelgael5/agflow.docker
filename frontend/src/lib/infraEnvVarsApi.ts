import { api } from "./api";

export interface NamedTypeEnvVar {
  id: string;
  named_type_id: string;
  name: string;
  description: string;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface NamedTypeEnvVarCreate {
  name: string;
  description?: string;
  position?: number;
}

export interface NamedTypeEnvVarUpdate {
  name?: string;
  description?: string;
  position?: number;
}

export interface MachineEnvVar {
  id: string;
  machine_id: string;
  named_type_env_var_id: string;
  name: string;
  description: string;
  value: string;
  created_at: string;
  updated_at: string;
}

export interface MachineEnvVarUpsert {
  values: Record<string, string>;
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
  missing_env_vars: string[];
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
