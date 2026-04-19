import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  infraTypesApi,
  infraCertificatesApi,
  type CertificateCreatePayload,
} from "@/lib/infraApi";

export function useInfraTypes(type?: "platform" | "service") {
  return useQuery({
    queryKey: ["infra-types", type ?? "all"],
    queryFn: () => infraTypesApi.list(type),
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
