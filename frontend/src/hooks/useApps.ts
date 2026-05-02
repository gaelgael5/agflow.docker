import { useQuery } from "@tanstack/react-query";
import { appsApi } from "@/lib/appsApi";

export function useApps() {
  return useQuery({
    queryKey: ["apps"],
    queryFn: () => appsApi.list(),
    // Le contenu apps.json change rarement (édité côté ops). Pas de polling.
    staleTime: 5 * 60 * 1000,
  });
}
