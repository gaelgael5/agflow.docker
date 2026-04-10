import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  secretsApi,
  type SecretCreate,
  type SecretSummary,
  type SecretUpdate,
} from "@/lib/secretsApi";

const SECRETS_KEY = ["secrets"] as const;

export function useSecrets() {
  const qc = useQueryClient();

  const listQuery = useQuery<SecretSummary[]>({
    queryKey: SECRETS_KEY,
    queryFn: () => secretsApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (payload: SecretCreate) => secretsApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: SECRETS_KEY }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: SecretUpdate }) =>
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
    createMutation,
    updateMutation,
    deleteMutation,
  };
}
