import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  secretsApi,
  type CreateEnvPayload,
  type CreateVaultPayload,
  type UpdateSecretPayload,
  type PlatformSecretSummary,
} from "@/lib/secretsApi";

const SECRETS_KEY = ["secrets"] as const;

export function useSecrets() {
  const qc = useQueryClient();

  const listQuery = useQuery<PlatformSecretSummary[]>({
    queryKey: SECRETS_KEY,
    queryFn: () => secretsApi.list(),
  });

  const createVaultMutation = useMutation({
    mutationFn: (payload: CreateVaultPayload) => secretsApi.createVault(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: SECRETS_KEY }),
  });

  const createEnvMutation = useMutation({
    mutationFn: (payload: CreateEnvPayload) => secretsApi.createEnv(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: SECRETS_KEY }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateSecretPayload }) =>
      secretsApi.update(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: SECRETS_KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => secretsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: SECRETS_KEY }),
  });

  return {
    secrets: listQuery.data,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    createVaultMutation,
    createEnvMutation,
    updateMutation,
    deleteMutation,
  };
}
