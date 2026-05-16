import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  harpocrateVaultsApi,
  type CreateVaultPayload,
  type HarpocrateVaultSummary,
  type UpdateVaultPayload,
} from "@/lib/harpocrateVaultsApi";

const VAULTS_KEY = ["harpocrate-vaults"] as const;

export function useHarpocrateVaults() {
  const qc = useQueryClient();

  const listQuery = useQuery<HarpocrateVaultSummary[]>({
    queryKey: VAULTS_KEY,
    queryFn: () => harpocrateVaultsApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (payload: CreateVaultPayload) => harpocrateVaultsApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: VAULTS_KEY }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateVaultPayload }) =>
      harpocrateVaultsApi.update(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: VAULTS_KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => harpocrateVaultsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: VAULTS_KEY }),
  });

  const setDefaultMutation = useMutation({
    mutationFn: (id: string) => harpocrateVaultsApi.setDefault(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: VAULTS_KEY }),
  });

  const defaultVault: HarpocrateVaultSummary | undefined =
    listQuery.data?.find((v) => v.is_default);

  return {
    vaults: listQuery.data ?? [],
    defaultVault,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
    setDefault: setDefaultMutation.mutateAsync,
  };
}
