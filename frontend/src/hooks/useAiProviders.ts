import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { aiProvidersApi, type ProviderCreatePayload } from "@/lib/aiProvidersApi";

const KEY = ["ai-providers"] as const;

export function useAiProviders() {
  const qc = useQueryClient();

  const listQuery = useQuery({
    queryKey: KEY,
    queryFn: () => aiProvidersApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (p: ProviderCreatePayload) => aiProvidersApi.create(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: ({ serviceType, providerName }: { serviceType: string; providerName: string }) =>
      aiProvidersApi.remove(serviceType, providerName),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  return {
    providers: listQuery.data,
    isLoading: listQuery.isLoading,
    createMutation,
    deleteMutation,
  };
}
