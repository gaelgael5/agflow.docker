import { api } from "./api";

// ── Projects ────────────────────────────────────────────

export interface ProjectSummary {
  id: string;
  display_name: string;
  description: string;
  environment: "dev" | "staging" | "prod";
  tags: string[];
  group_count: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreatePayload {
  display_name: string;
  description?: string;
  environment?: "dev" | "staging" | "prod";
  tags?: string[];
}

export const projectsApi = {
  async list(): Promise<ProjectSummary[]> {
    return (await api.get<ProjectSummary[]>("/admin/projects")).data;
  },
  async get(id: string): Promise<ProjectSummary> {
    return (await api.get<ProjectSummary>(`/admin/projects/${id}`)).data;
  },
  async create(p: ProjectCreatePayload): Promise<ProjectSummary> {
    return (await api.post<ProjectSummary>("/admin/projects", p)).data;
  },
  async update(id: string, p: Partial<ProjectCreatePayload>): Promise<ProjectSummary> {
    return (await api.put<ProjectSummary>(`/admin/projects/${id}`, p)).data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/projects/${id}`);
  },
};

// ── Groups ──────────────────────────────────────────────

export interface GroupSummary {
  id: string;
  project_id: string;
  name: string;
  max_agents: number;
  instance_count: number;
  created_at: string;
  updated_at: string;
}

export interface GroupCreatePayload {
  project_id: string;
  name: string;
  max_agents?: number;
}

export const groupsApi = {
  async listByProject(projectId: string): Promise<GroupSummary[]> {
    return (await api.get<GroupSummary[]>("/admin/groups", { params: { project_id: projectId } })).data;
  },
  async get(id: string): Promise<GroupSummary> {
    return (await api.get<GroupSummary>(`/admin/groups/${id}`)).data;
  },
  async create(p: GroupCreatePayload): Promise<GroupSummary> {
    return (await api.post<GroupSummary>("/admin/groups", p)).data;
  },
  async update(id: string, p: Partial<GroupCreatePayload>): Promise<GroupSummary> {
    return (await api.put<GroupSummary>(`/admin/groups/${id}`, p)).data;
  },
  async availableServices(id: string): Promise<AvailableService[]> {
    return (await api.get<{ services: AvailableService[] }>(`/admin/groups/${id}/available-services`)).data.services;
  },
  async preview(id: string): Promise<GroupPreview> {
    return (await api.get<GroupPreview>(`/admin/groups/${id}/preview`)).data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/groups/${id}`);
  },
};

export interface AvailableService {
  instance_id: string;
  instance_name: string;
  catalog_id: string;
  service_id: string;
  container_name: string;
  image: string;
  ports: number[];
}

// ── Deployments ─────────────────────────────────────────

export interface DeploymentSummary {
  id: string;
  project_id: string;
  user_id: string;
  group_servers: Record<string, string>;
  status: "draft" | "generated" | "deployed";
  generated_compose: string | null;
  generated_env: string | null;
  nullable_secrets: string[];
  created_at: string;
  updated_at: string;
}

export const deploymentsApi = {
  async listByProject(projectId: string): Promise<DeploymentSummary[]> {
    return (await api.get<DeploymentSummary[]>("/admin/project-deployments", { params: { project_id: projectId } })).data;
  },
  async get(id: string): Promise<DeploymentSummary> {
    return (await api.get<DeploymentSummary>(`/admin/project-deployments/${id}`)).data;
  },
  async create(projectId: string, groupServers: Record<string, string>): Promise<DeploymentSummary> {
    return (await api.post<DeploymentSummary>("/admin/project-deployments", { project_id: projectId, group_servers: groupServers })).data;
  },
  async update(id: string, groupServers: Record<string, string>): Promise<DeploymentSummary> {
    return (await api.put<DeploymentSummary>(`/admin/project-deployments/${id}`, { group_servers: groupServers })).data;
  },
  async generate(id: string, userSecrets?: Record<string, string>): Promise<DeploymentSummary> {
    return (await api.post<DeploymentSummary>(`/admin/project-deployments/${id}/generate`, { user_secrets: userSecrets ?? {} })).data;
  },
  async push(id: string): Promise<{ results: PushResult[] }> {
    return (await api.post<{ results: PushResult[] }>(`/admin/project-deployments/${id}/push`)).data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/project-deployments/${id}`);
  },
};

export interface PushResult {
  server: string;
  success: boolean;
  stdout?: string;
  stderr?: string;
  error?: string;
}

export interface GroupPreview {
  yaml: string;
  secret_refs: string[];
  resolved_secrets: string[];
  unresolved_secrets: string[];
}

// ── Instances ───────────────────────────────────────────

export interface InstanceSummary {
  id: string;
  group_id: string;
  instance_name: string;
  catalog_id: string;
  variables: Record<string, string>;
  status: "draft" | "active" | "stopped";
  service_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface InstanceCreatePayload {
  group_id: string;
  instance_name: string;
  catalog_id: string;
  variables?: Record<string, string>;
}

export const instancesApi = {
  async listByGroup(groupId: string): Promise<InstanceSummary[]> {
    return (await api.get<InstanceSummary[]>("/admin/product-instances", { params: { group_id: groupId } })).data;
  },
  async listByProject(projectId: string): Promise<InstanceSummary[]> {
    return (await api.get<InstanceSummary[]>("/admin/product-instances", { params: { project_id: projectId } })).data;
  },
  async get(id: string): Promise<InstanceSummary> {
    return (await api.get<InstanceSummary>(`/admin/product-instances/${id}`)).data;
  },
  async create(p: InstanceCreatePayload): Promise<InstanceSummary> {
    return (await api.post<InstanceSummary>("/admin/product-instances", p)).data;
  },
  async update(id: string, p: Partial<InstanceCreatePayload> & { service_url?: string }): Promise<InstanceSummary> {
    return (await api.put<InstanceSummary>(`/admin/product-instances/${id}`, p)).data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/product-instances/${id}`);
  },
  async activate(id: string, serviceUrl: string): Promise<InstanceSummary> {
    return (await api.post<{ instance: InstanceSummary }>(`/admin/product-instances/${id}/activate`, { service_url: serviceUrl })).data.instance;
  },
  async stop(id: string): Promise<InstanceSummary> {
    return (await api.post<InstanceSummary>(`/admin/product-instances/${id}/stop`)).data;
  },
};
