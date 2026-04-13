import { useQuery } from "@tanstack/react-query";
import { apiKeysApi, type ScopeGroup } from "@/lib/apiKeysApi";

export function useScopes() {
  const query = useQuery<ScopeGroup[]>({
    queryKey: ["scopes"],
    queryFn: () => apiKeysApi.listScopes(),
    staleTime: 5 * 60 * 1000,
  });

  const allScopes: string[] =
    query.data?.flatMap((g) => g.scopes) ?? [];

  return { groups: query.data ?? [], allScopes, isLoading: query.isLoading };
}
