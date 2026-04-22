import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  infraCategoriesApi,
  infraCertificatesApi,
  infraMachinesApi,
  infraNamedTypeActionsApi,
  infraNamedTypesApi,
  type CertificateCreatePayload,
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
