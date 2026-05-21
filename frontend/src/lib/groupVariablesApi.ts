import { api } from "./api";

export interface GroupVariable {
  id: string;
  group_id: string;
  name: string;
  value: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface GroupVariableCreatePayload {
  name: string;
  value?: string;
  description?: string;
}

export interface GroupVariableUpdatePayload {
  name?: string;
  value?: string;
  description?: string;
}

export const groupVariablesApi = {
  async list(groupId: string): Promise<GroupVariable[]> {
    return (await api.get<GroupVariable[]>(
      `/admin/groups/${groupId}/variables`,
    )).data;
  },
  async create(groupId: string, p: GroupVariableCreatePayload): Promise<GroupVariable> {
    return (await api.post<GroupVariable>(
      `/admin/groups/${groupId}/variables`,
      p,
    )).data;
  },
  async update(
    groupId: string,
    varId: string,
    p: GroupVariableUpdatePayload,
  ): Promise<GroupVariable> {
    return (await api.put<GroupVariable>(
      `/admin/groups/${groupId}/variables/${varId}`,
      p,
    )).data;
  },
  async remove(groupId: string, varId: string): Promise<void> {
    await api.delete(`/admin/groups/${groupId}/variables/${varId}`);
  },
};
