import { api } from "./api";

export type BuildStatus = "pending" | "running" | "success" | "failed";
export type DisplayStatus =
  | "never_built"
  | "up_to_date"
  | "outdated"
  | "failed"
  | "building";

export interface DockerfileSummary {
  id: string;
  display_name: string;
  description: string;
  parameters: Record<string, unknown>;
  current_hash: string;
  display_status: DisplayStatus;
  latest_build_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface FileSummary {
  id: string;
  dockerfile_id: string;
  path: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface DockerfileDetail {
  dockerfile: DockerfileSummary;
  files: FileSummary[];
}

export interface BuildSummary {
  id: string;
  dockerfile_id: string;
  content_hash: string;
  image_tag: string;
  status: BuildStatus;
  logs: string;
  started_at: string;
  finished_at: string | null;
}

export interface DockerfileCreate {
  id: string;
  display_name: string;
  description?: string;
  parameters?: Record<string, unknown>;
}

export interface MountCheckResult {
  source_original: string;
  source_resolved: string;
  auto_prefixed: boolean;
  exists: boolean | null;
}

export interface MountCheckResponse {
  results: MountCheckResult[];
}

export interface FileCreate {
  path: string;
  content?: string;
}

export const dockerfilesApi = {
  async list(): Promise<DockerfileSummary[]> {
    const res = await api.get<DockerfileSummary[]>("/admin/dockerfiles");
    return res.data;
  },
  async get(id: string): Promise<DockerfileDetail> {
    const res = await api.get<DockerfileDetail>(`/admin/dockerfiles/${id}`);
    return res.data;
  },
  async create(payload: DockerfileCreate): Promise<DockerfileSummary> {
    const res = await api.post<DockerfileSummary>("/admin/dockerfiles", payload);
    return res.data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/dockerfiles/${id}`);
  },
  async createFile(
    dockerfileId: string,
    payload: FileCreate,
  ): Promise<FileSummary> {
    const res = await api.post<FileSummary>(
      `/admin/dockerfiles/${dockerfileId}/files`,
      payload,
    );
    return res.data;
  },
  async updateFile(
    dockerfileId: string,
    fileId: string,
    content: string,
  ): Promise<FileSummary> {
    const res = await api.put<FileSummary>(
      `/admin/dockerfiles/${dockerfileId}/files/${fileId}`,
      { content },
    );
    return res.data;
  },
  async deleteFile(dockerfileId: string, fileId: string): Promise<void> {
    await api.delete(`/admin/dockerfiles/${dockerfileId}/files/${fileId}`);
  },
  async build(dockerfileId: string): Promise<BuildSummary> {
    const res = await api.post<BuildSummary>(
      `/admin/dockerfiles/${dockerfileId}/build`,
    );
    return res.data;
  },
  async getBuild(dockerfileId: string, buildId: string): Promise<BuildSummary> {
    const res = await api.get<BuildSummary>(
      `/admin/dockerfiles/${dockerfileId}/builds/${buildId}`,
    );
    return res.data;
  },
  async exportZip(dockerfileId: string): Promise<Blob> {
    const res = await api.get<Blob>(
      `/admin/dockerfiles/${dockerfileId}/export`,
      { responseType: "blob" },
    );
    return res.data;
  },
  async checkMounts(
    dockerfileId: string,
    payload: {
      mounts: { source: string; target: string; readonly: boolean }[];
      params: Record<string, string>;
    },
  ): Promise<MountCheckResponse> {
    const res = await api.post<MountCheckResponse>(
      `/admin/dockerfiles/${dockerfileId}/check-mounts`,
      payload,
    );
    return res.data;
  },
  async importZip(
    dockerfileId: string,
    file: File,
  ): Promise<DockerfileDetail> {
    const form = new FormData();
    form.append("file", file);
    const res = await api.post<DockerfileDetail>(
      `/admin/dockerfiles/${dockerfileId}/import`,
      form,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    return res.data;
  },
};
