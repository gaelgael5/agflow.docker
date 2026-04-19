import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { productsApi, type ProductCreatePayload } from "@/lib/productsApi";

const KEY = ["products"] as const;

export function useProducts() {
  const qc = useQueryClient();

  const listQuery = useQuery({
    queryKey: KEY,
    queryFn: () => productsApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (p: ProductCreatePayload) => productsApi.create(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => productsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  return {
    products: listQuery.data,
    isLoading: listQuery.isLoading,
    createMutation,
    deleteMutation,
  };
}
