import { api } from "./api";

export type RuntimeStatus = "pending" | "deployed" | "failed";

export interface ProjectGroupRuntime {
  id: string;
  seq: number;
  project_runtime_id: string;
  group_id: string;
  group_name: string;
  machine_id: string | null;
  machine_name: string;
  remote_path: string;
  status: RuntimeStatus;
  pushed_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectGroupRuntimeDetail extends ProjectGroupRuntime {
  env_text: string;
  compose_yaml: string;
}

export interface ProjectRuntime {
  id: string;
  seq: number;
  project_id: string;
  deployment_id: string | null;
  user_id: string | null;
  user_email: string | null;
  status: RuntimeStatus;
  pushed_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  group_runtimes: ProjectGroupRuntime[];
}

export interface RuntimeRuntimeStatus {
  runtime_id: string;
  machine_id: string;
  overall_state: "running" | "partial" | "stopped" | "mixed" | "unknown";
  containers: Array<{ ID?: string; Names?: string; Image?: string; State?: string; Status?: string }>;
}

export const runtimesApi = {
  async listByGroup(groupId: string): Promise<ProjectGroupRuntime[]> {
    return (await api.get<ProjectGroupRuntime[]>(`/admin/groups/${groupId}/runtimes`)).data;
  },
  async listByProject(projectId: string): Promise<ProjectRuntime[]> {
    return (await api.get<ProjectRuntime[]>(`/admin/projects/${projectId}/runtimes`)).data;
  },
  async get(runtimeId: string): Promise<ProjectGroupRuntimeDetail> {
    return (await api.get<ProjectGroupRuntimeDetail>(`/admin/group-runtimes/${runtimeId}`)).data;
  },
  async status(runtimeId: string): Promise<RuntimeRuntimeStatus> {
    return (await api.get<RuntimeRuntimeStatus>(`/admin/group-runtimes/${runtimeId}/status`)).data;
  },
  async start(runtimeId: string): Promise<{ exit_code: number; stdout: string; stderr: string }> {
    return (await api.post(`/admin/group-runtimes/${runtimeId}/start`)).data;
  },
  async stop(runtimeId: string): Promise<{ exit_code: number; stdout: string; stderr: string }> {
    return (await api.post(`/admin/group-runtimes/${runtimeId}/stop`)).data;
  },
  async remove(runtimeId: string): Promise<void> {
    await api.delete(`/admin/group-runtimes/${runtimeId}`);
  },
};
