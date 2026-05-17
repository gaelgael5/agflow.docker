import { useQuery } from "@tanstack/react-query";
import {
  supervisionApi,
  type SupervisedInstance,
} from "@/lib/supervisionApi";

const REFETCH_MS = 5_000;

export function useOverview() {
  return useQuery({
    queryKey: ["supervision", "overview"],
    queryFn: () => supervisionApi.getOverview(),
    refetchInterval: REFETCH_MS,
  });
}

interface UseInstancesParams {
  status: "idle" | "busy" | "error" | undefined;
  includeDestroyed: boolean;
}

export function useInstances({ status, includeDestroyed }: UseInstancesParams) {
  return useQuery({
    queryKey: ["supervision", "instances", { status, includeDestroyed }],
    queryFn: async (): Promise<SupervisedInstance[]> => {
      const alive = await supervisionApi.listInstances({ status, limit: 200 });
      if (!includeDestroyed) return alive;
      const destroyed = await supervisionApi.listInstances({
        status: "destroyed",
        limit: 200,
      });
      return [...alive, ...destroyed];
    },
    refetchInterval: REFETCH_MS,
  });
}

export function useInstanceDetail(id: string | null) {
  return useQuery({
    queryKey: ["supervision", "instance", id],
    queryFn: () => supervisionApi.getInstance(id as string),
    enabled: !!id,
    refetchInterval: REFETCH_MS,
  });
}
