import { api } from "./api";

export type SessionStatus = "active" | "closed" | "expired";

export interface SessionListItem {
  id: string;
  name: string | null;
  status: SessionStatus;
  project_id: string | null;
  created_at: string;
  expires_at: string;
  closed_at: string | null;
  api_key_id: string;
  agent_count: number;
}

export interface SessionDetail {
  id: string;
  name: string | null;
  status: SessionStatus;
  project_id: string | null;
  created_at: string;
  expires_at: string;
  closed_at: string | null;
  api_key_id: string;
}

export type AgentInstanceStatus = "busy" | "idle";

export interface AgentInstance {
  id: string;
  session_id: string;
  agent_id: string;
  labels: Record<string, unknown>;
  mission: string | null;
  status: AgentInstanceStatus;
  created_at: string;
}

export type MessageKind =
  | "llm_call"
  | "tool_call"
  | "mcp_call"
  | "file_change"
  | "error"
  | "instruction"
  | "event"
  | string;

export type MessageDirection = "in" | "out";

export interface MomMessage {
  msg_id: string;
  parent_msg_id: string | null;
  direction: MessageDirection;
  kind: MessageKind;
  payload: unknown;
  source: string | null;
  created_at: string;
  route: unknown;
}

export interface ListMessagesOptions {
  kind?: string;
  direction?: MessageDirection;
  limit?: number;
}

export const sessionsApi = {
  async list(projectId?: string): Promise<SessionListItem[]> {
    const params = projectId ? { project_id: projectId } : undefined;
    return (await api.get<SessionListItem[]>("/admin/sessions", { params })).data;
  },
  async get(id: string): Promise<SessionDetail> {
    return (await api.get<SessionDetail>(`/admin/sessions/${id}`)).data;
  },
  async listAgents(sessionId: string): Promise<AgentInstance[]> {
    return (await api.get<AgentInstance[]>(`/admin/sessions/${sessionId}/agents`)).data;
  },
  async listMessages(
    sessionId: string,
    instanceId: string,
    opts?: ListMessagesOptions,
  ): Promise<MomMessage[]> {
    return (
      await api.get<MomMessage[]>(
        `/admin/sessions/${sessionId}/agents/${instanceId}/messages`,
        { params: opts },
      )
    ).data;
  },
};
