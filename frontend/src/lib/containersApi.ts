import { api } from "./api";

export type ContainerStatus =
  | "created"
  | "running"
  | "restarting"
  | "removing"
  | "paused"
  | "exited"
  | "dead";

export interface ContainerInfo {
  id: string;
  name: string;
  dockerfile_id: string;
  image: string;
  status: ContainerStatus;
  created_at: string;
  instance_id: string;
}

export const containersApi = {
  async list(): Promise<ContainerInfo[]> {
    const res = await api.get<ContainerInfo[]>("/admin/containers");
    return res.data;
  },
  async run(
    dockerfileId: string,
    secrets?: Record<string, string>,
  ): Promise<ContainerInfo> {
    const res = await api.post<ContainerInfo>(
      `/admin/dockerfiles/${dockerfileId}/run`,
      { secrets: secrets ?? {} },
    );
    return res.data;
  },
  async stop(containerId: string): Promise<void> {
    await api.delete(`/admin/containers/${containerId}`);
  },
};
