import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  serviceTypesApi,
  type ServiceTypeCreate,
  type ServiceTypeSummary,
} from "@/lib/serviceTypesApi";

const KEY = ["service-types"] as const;

export function useServiceTypes() {
  const qc = useQueryClient();

  const listQuery = useQuery<ServiceTypeSummary[]>({
    queryKey: KEY,
    queryFn: () => serviceTypesApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (payload: ServiceTypeCreate) => serviceTypesApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (name: string) => serviceTypesApi.remove(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  return {
    serviceTypes: listQuery.data,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    createMutation,
    deleteMutation,
  };
}
