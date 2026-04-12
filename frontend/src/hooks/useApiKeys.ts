import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  apiKeysApi,
  type ApiKeyCreate,
  type ApiKeySummary,
  type ApiKeyUpdate,
} from "@/lib/apiKeysApi";

const API_KEYS_KEY = ["apiKeys"] as const;

export function useApiKeys() {
  const qc = useQueryClient();

  const listQuery = useQuery<ApiKeySummary[]>({
    queryKey: API_KEYS_KEY,
    queryFn: () => apiKeysApi.list(),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: API_KEYS_KEY });
  };

  const createMutation = useMutation({
    mutationFn: (payload: ApiKeyCreate) => apiKeysApi.create(payload),
    onSuccess: invalidate,
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: ApiKeyUpdate }) =>
      apiKeysApi.update(id, payload),
    onSuccess: invalidate,
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => apiKeysApi.revoke(id),
    onSuccess: invalidate,
  });

  return {
    apiKeys: listQuery.data,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    createMutation,
    updateMutation,
    revokeMutation,
  };
}

export function useApiKeyDetail(id: string | null) {
  return useQuery<ApiKeySummary>({
    queryKey: ["apiKey", id],
    queryFn: () => {
      if (!id) throw new Error("id required");
      return apiKeysApi.get(id);
    },
    enabled: !!id,
  });
}
