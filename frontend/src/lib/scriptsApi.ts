import { api } from "./api";

// ── Scripts (shell .sh stocké en BDD) ─────────────────

export type InputStatus = "keep" | "clean" | "replace";

export interface ScriptInputVariable {
  name: string;
  description: string;
  default: string;
}

export interface ScriptSummary {
  id: string;
  name: string;
  description: string;
  execute_on_types_named: string | null;
  execute_on_types_named_name: string | null;
  input_variables: ScriptInputVariable[];
  created_at: string;
  updated_at: string;
}

export interface ScriptRow extends ScriptSummary {
  content: string;
}

export interface ScriptCreatePayload {
  name: string;
  description?: string;
  content?: string;
  execute_on_types_named?: string | null;
  input_variables?: ScriptInputVariable[];
}

export interface ScriptUpdatePayload {
  name?: string;
  description?: string;
  content?: string;
  execute_on_types_named?: string | null;
  input_variables?: ScriptInputVariable[];
}

export const scriptsApi = {
  async list(): Promise<ScriptSummary[]> {
    return (await api.get<ScriptSummary[]>("/admin/scripts")).data;
  },
  async get(id: string): Promise<ScriptRow> {
    return (await api.get<ScriptRow>(`/admin/scripts/${id}`)).data;
  },
  async create(p: ScriptCreatePayload): Promise<ScriptRow> {
    return (await api.post<ScriptRow>("/admin/scripts", p)).data;
  },
  async update(id: string, p: ScriptUpdatePayload): Promise<ScriptRow> {
    return (await api.put<ScriptRow>(`/admin/scripts/${id}`, p)).data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/scripts/${id}`);
  },
};

// ── group_scripts (reference script dans un groupe) ───

export type ScriptTiming = "before" | "after";

export type TriggerOp = "equals" | "not_equals" | "is_null";

export interface TriggerRule {
  variable: string;
  op: TriggerOp;
  value: string;
}

export interface GroupScript {
  id: string;
  group_id: string;
  group_name: string;
  script_id: string;
  script_name: string;
  machine_id: string;
  machine_name: string;
  timing: ScriptTiming;
  position: number;
  env_mapping: Record<string, string>;
  input_values: Record<string, string>;
  input_statuses: Record<string, InputStatus>;
  trigger_rules: TriggerRule[];
  created_at: string;
  updated_at: string;
}

export interface GroupScriptCreatePayload {
  script_id: string;
  machine_id: string;
  timing: ScriptTiming;
  position?: number;
  env_mapping?: Record<string, string>;
  input_values?: Record<string, string>;
  input_statuses?: Record<string, InputStatus>;
  trigger_rules?: TriggerRule[];
}

export interface GroupScriptUpdatePayload {
  script_id?: string;
  machine_id?: string;
  timing?: ScriptTiming;
  position?: number;
  env_mapping?: Record<string, string>;
  input_values?: Record<string, string>;
  input_statuses?: Record<string, InputStatus>;
  trigger_rules?: TriggerRule[];
}

export const groupScriptsApi = {
  async list(groupId: string): Promise<GroupScript[]> {
    return (await api.get<GroupScript[]>(`/admin/groups/${groupId}/scripts`)).data;
  },
  async create(groupId: string, p: GroupScriptCreatePayload): Promise<GroupScript> {
    return (await api.post<GroupScript>(`/admin/groups/${groupId}/scripts`, p)).data;
  },
  async update(groupId: string, linkId: string, p: GroupScriptUpdatePayload): Promise<GroupScript> {
    return (await api.put<GroupScript>(`/admin/groups/${groupId}/scripts/${linkId}`, p)).data;
  },
  async remove(groupId: string, linkId: string): Promise<void> {
    await api.delete(`/admin/groups/${groupId}/scripts/${linkId}`);
  },
};
