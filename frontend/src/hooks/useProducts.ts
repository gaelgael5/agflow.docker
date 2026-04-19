import { useQuery } from "@tanstack/react-query";
import { productsApi } from "@/lib/productsApi";

const KEY = ["products"] as const;

export function useProducts() {
  const listQuery = useQuery({
    queryKey: KEY,
    queryFn: () => productsApi.list(),
  });

  return {
    products: listQuery.data,
    isLoading: listQuery.isLoading,
  };
}
