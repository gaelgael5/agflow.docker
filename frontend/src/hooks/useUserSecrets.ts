import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  userSecretsApi,
  type UserSecretCreate,
  type UserSecretSummary,
  type UserSecretUpdate,
} from "@/lib/userSecretsApi";

const SECRETS_KEY = ["user-secrets"] as const;

export function useUserSecrets() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: SECRETS_KEY });

  const listQuery = useQuery<UserSecretSummary[]>({
    queryKey: SECRETS_KEY,
    queryFn: () => userSecretsApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (payload: UserSecretCreate) => userSecretsApi.create(payload),
    onSuccess: invalidate,
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UserSecretUpdate }) =>
      userSecretsApi.update(id, payload),
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => userSecretsApi.remove(id),
    onSuccess: invalidate,
  });

  return {
    secrets: listQuery.data,
    isLoading: listQuery.isLoading,
    createMutation,
    updateMutation,
    deleteMutation,
  };
}
