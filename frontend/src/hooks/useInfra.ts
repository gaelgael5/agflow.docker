import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  infraCategoriesApi,
  infraCertificatesApi,
  infraMachinesApi,
  infraNamedTypeActionsApi,
  infraNamedTypeRulesApi,
  infraNamedTypesApi,
  infraRuntimeConfigApi,
  type CertificateCreatePayload,
  type NamedTypeRule,
  type RuntimeConfigEntry,
} from "@/lib/infraApi";

export function useInfraCategories() {
  return useQuery({
    queryKey: ["infra-categories"],
    queryFn: () => infraCategoriesApi.list(),
  });
}

export function useInfraCategoryActions(category: string | null | undefined) {
  return useQuery({
    queryKey: ["infra-category-actions", category ?? ""],
    queryFn: () => infraCategoriesApi.listActions(category as string),
    enabled: !!category,
  });
}

export function useInfraNamedTypes() {
  return useQuery({
    queryKey: ["infra-named-types"],
    queryFn: () => infraNamedTypesApi.list(),
  });
}

export function useInfraNamedTypeActions(namedTypeId: string | null | undefined) {
  return useQuery({
    queryKey: ["infra-named-type-actions", namedTypeId ?? ""],
    queryFn: () => infraNamedTypeActionsApi.list(namedTypeId as string),
    enabled: !!namedTypeId,
  });
}

export function useRuntimeConfig() {
  return useQuery({
    queryKey: ["infra-runtime-config"],
    queryFn: () => infraRuntimeConfigApi.list(),
    staleTime: 60_000,
  });
}

export function useNamedTypeRules(namedTypeId: string | null | undefined) {
  return useQuery({
    queryKey: ["infra-named-type-rules", namedTypeId ?? ""],
    queryFn: () => infraNamedTypeRulesApi.list(namedTypeId as string),
    enabled: !!namedTypeId,
  });
}

export function useAllNamedTypeRules() {
  return useQuery({
    queryKey: ["infra-named-type-rules-all"],
    queryFn: () => infraNamedTypeRulesApi.listAll(),
  });
}

export function filterNamedTypesByRules(
  namedTypeIds: string[],
  rules: NamedTypeRule[],
  runtimeConfig: RuntimeConfigEntry[],
): Set<string> {
  const configMap = new Map(runtimeConfig.map((e) => [e.key, e.value]));
  const rulesByNamedType = new Map<string, NamedTypeRule[]>();
  for (const rule of rules) {
    const id = String(rule.named_type_id);
    if (!rulesByNamedType.has(id)) rulesByNamedType.set(id, []);
    rulesByNamedType.get(id)!.push(rule);
  }
  return new Set(
    namedTypeIds.filter((id) => {
      const ntRules = rulesByNamedType.get(id) ?? [];
      return ntRules.every((r) => configMap.get(r.key) === r.value);
    }),
  );
}

export function useInfraMachinesRuns(machineId: string | null | undefined) {
  return useQuery({
    queryKey: ["infra-machines-runs", machineId ?? ""],
    queryFn: () => infraMachinesApi.listRuns(machineId as string),
    enabled: !!machineId,
  });
}

export function useInfraCertificates() {
  const qc = useQueryClient();
  const KEY = ["infra-certificates"] as const;

  const listQuery = useQuery({
    queryKey: KEY,
    queryFn: () => infraCertificatesApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (p: CertificateCreatePayload) => infraCertificatesApi.create(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => infraCertificatesApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  return {
    certificates: listQuery.data,
    isLoading: listQuery.isLoading,
    createMutation,
    deleteMutation,
  };
}
