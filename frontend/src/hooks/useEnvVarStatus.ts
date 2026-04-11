import { useQuery } from "@tanstack/react-query";
import {
  secretsApi,
  type EnvVarStatus,
  type EnvVarStatusMap,
} from "@/lib/secretsApi";

/**
 * Batch-resolve the status (missing / empty / ok) of a set of env var names.
 * Returns an empty map while loading or when `names` is empty — callers should
 * fall back to "missing" when a key is absent.
 *
 * The sorted cache key lets multiple components asking for the same set
 * share a single request. For sporadic partial overlaps, use the same
 * deduped array reference or accept that 2 requests will fire.
 */
export function useEnvVarStatuses(names: string[]) {
  const dedup = Array.from(new Set(names.filter((n) => n.trim().length > 0)));
  dedup.sort();

  return useQuery<EnvVarStatusMap>({
    queryKey: ["env-var-status", dedup],
    queryFn: () => secretsApi.resolveStatus(dedup),
    enabled: dedup.length > 0,
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  });
}

/**
 * Convenience helper for a single name. Returns `undefined` while loading.
 */
export function useEnvVarStatus(name: string | null | undefined): EnvVarStatus | undefined {
  const query = useEnvVarStatuses(name ? [name] : []);
  if (!name) return undefined;
  return query.data?.[name];
}
