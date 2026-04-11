import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  agentsApi,
  type AgentCreatePayload,
  type AgentDetail,
  type AgentSummary,
  type AgentUpdatePayload,
  type ConfigPreview,
} from "@/lib/agentsApi";

const AGENTS_KEY = ["agents"] as const;
const AGENT_KEY = (id: string) => ["agents", id] as const;

export function useAgents() {
  const qc = useQueryClient();

  const listQuery = useQuery<AgentSummary[]>({
    queryKey: AGENTS_KEY,
    queryFn: () => agentsApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (payload: AgentCreatePayload) => agentsApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: AGENTS_KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => agentsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: AGENTS_KEY }),
  });

  const duplicateMutation = useMutation({
    mutationFn: ({
      id,
      slug,
      displayName,
    }: {
      id: string;
      slug: string;
      displayName: string;
    }) => agentsApi.duplicate(id, slug, displayName),
    onSuccess: () => qc.invalidateQueries({ queryKey: AGENTS_KEY }),
  });

  return {
    agents: listQuery.data,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    createMutation,
    deleteMutation,
    duplicateMutation,
  };
}

export function useAgent(id: string | undefined) {
  const qc = useQueryClient();

  const detailQuery = useQuery<AgentDetail>({
    queryKey: id ? AGENT_KEY(id) : ["agents", "none"],
    queryFn: () => agentsApi.get(id!),
    enabled: Boolean(id),
  });

  const updateMutation = useMutation({
    mutationFn: (payload: AgentUpdatePayload) => agentsApi.update(id!, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: AGENTS_KEY });
      if (id) qc.invalidateQueries({ queryKey: AGENT_KEY(id) });
    },
  });

  return {
    agent: detailQuery.data,
    isLoading: detailQuery.isLoading,
    error: detailQuery.error,
    updateMutation,
  };
}

export function useConfigPreview(id: string | undefined) {
  return useQuery<ConfigPreview>({
    queryKey: id ? ["agents", id, "config-preview"] : ["agents", "none"],
    queryFn: () => agentsApi.configPreview(id!),
    enabled: false,
  });
}
