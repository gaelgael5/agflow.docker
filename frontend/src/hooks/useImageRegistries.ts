import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { imageRegistriesApi, type RegistryCreatePayload } from "@/lib/imageRegistriesApi";

const KEY = ["image-registries"] as const;

export function useImageRegistries() {
  const qc = useQueryClient();

  const listQuery = useQuery({
    queryKey: KEY,
    queryFn: () => imageRegistriesApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (p: RegistryCreatePayload) => imageRegistriesApi.create(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => imageRegistriesApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  return {
    registries: listQuery.data,
    isLoading: listQuery.isLoading,
    createMutation,
    deleteMutation,
  };
}
