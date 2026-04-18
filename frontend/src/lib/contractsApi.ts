import { api } from "@/lib/api";

export interface TagSummary {
  slug: string;
  name: string;
  description: string;
  operation_count: number;
}

export interface ContractSummary {
  id: string;
  agent_id: string;
  slug: string;
  display_name: string;
  description: string;
  source_type: "upload" | "url" | "manual";
  source_url: string | null;
  base_url: string;
  auth_header: string;
  auth_prefix: string;
  auth_secret_ref: string | null;
  parsed_tags: TagSummary[];
  output_dir: string;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface ContractDetail extends ContractSummary {
  spec_content: string;
}

export interface ContractCreatePayload {
  slug: string;
  display_name: string;
  description?: string;
  source_type?: "upload" | "url" | "manual";
  source_url?: string;
  spec_content: string;
  base_url?: string;
  auth_header?: string;
  auth_prefix?: string;
  auth_secret_ref?: string;
  output_dir?: string;
}

export interface ContractUpdatePayload {
  display_name?: string;
  description?: string;
  source_url?: string;
  spec_content?: string;
  base_url?: string;
  auth_header?: string;
  auth_prefix?: string;
  auth_secret_ref?: string;
  output_dir?: string;
}

export const contractsApi = {
  async list(agentId: string): Promise<ContractSummary[]> {
    const res = await api.get<ContractSummary[]>(
      `/admin/agents/${agentId}/contracts`,
    );
    return res.data;
  },
  async get(agentId: string, contractId: string): Promise<ContractDetail> {
    const res = await api.get<ContractDetail>(
      `/admin/agents/${agentId}/contracts/${contractId}`,
    );
    return res.data;
  },
  async create(
    agentId: string,
    payload: ContractCreatePayload,
  ): Promise<ContractSummary> {
    const res = await api.post<ContractSummary>(
      `/admin/agents/${agentId}/contracts`,
      payload,
    );
    return res.data;
  },
  async update(
    agentId: string,
    contractId: string,
    payload: ContractUpdatePayload,
  ): Promise<ContractSummary> {
    const res = await api.put<ContractSummary>(
      `/admin/agents/${agentId}/contracts/${contractId}`,
      payload,
    );
    return res.data;
  },
  async remove(agentId: string, contractId: string): Promise<void> {
    await api.delete(`/admin/agents/${agentId}/contracts/${contractId}`);
  },
  async fetchSpec(
    agentId: string,
    url: string,
  ): Promise<{ content: string }> {
    const res = await api.post<{ content: string }>(
      `/admin/agents/${agentId}/contracts/fetch-spec`,
      { url },
    );
    return res.data;
  },
};
