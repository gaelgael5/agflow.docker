import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  contractsApi,
  type ContractCreatePayload,
  type ContractSummary,
} from "@/lib/contractsApi";

const CONTRACTS_KEY = (agentId: string) => ["contracts", agentId] as const;

export function useContracts(agentId: string | undefined) {
  const qc = useQueryClient();

  const listQuery = useQuery<ContractSummary[]>({
    queryKey: agentId ? CONTRACTS_KEY(agentId) : ["contracts", "none"],
    queryFn: () => contractsApi.list(agentId!),
    enabled: Boolean(agentId),
  });

  const createMutation = useMutation({
    mutationFn: (payload: ContractCreatePayload) =>
      contractsApi.create(agentId!, payload),
    onSuccess: () => {
      if (agentId) qc.invalidateQueries({ queryKey: CONTRACTS_KEY(agentId) });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (contractId: string) =>
      contractsApi.remove(agentId!, contractId),
    onSuccess: () => {
      if (agentId) qc.invalidateQueries({ queryKey: CONTRACTS_KEY(agentId) });
    },
  });

  return {
    contracts: listQuery.data,
    isLoading: listQuery.isLoading,
    createMutation,
    deleteMutation,
  };
}
