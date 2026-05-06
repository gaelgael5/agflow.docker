import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { userSecretsApi } from "@/lib/userSecretsApi";

const KEY = ["user-secrets"] as const;

export function useUserSecrets() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: KEY });

  const listQuery = useQuery({ queryKey: KEY, queryFn: userSecretsApi.list });

  const createMutation = useMutation({
    mutationFn: userSecretsApi.create,
    onSuccess: invalidate,
  });

  const updateMutation = useMutation({
    mutationFn: ({ name, value }: { name: string; value: string }) =>
      userSecretsApi.update(name, value),
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: userSecretsApi.remove,
    onSuccess: invalidate,
  });

  return { listQuery, createMutation, updateMutation, deleteMutation };
}
