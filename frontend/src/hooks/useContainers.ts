import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { containersApi, type ContainerInfo } from "@/lib/containersApi";

const CONTAINERS_KEY = ["containers"] as const;

export function useContainers() {
  const qc = useQueryClient();

  const listQuery = useQuery<ContainerInfo[]>({
    queryKey: CONTAINERS_KEY,
    queryFn: () => containersApi.list(),
    refetchInterval: 5_000,
  });

  const runMutation = useMutation({
    mutationFn: (dockerfileId: string) => containersApi.run(dockerfileId),
    onSuccess: () => qc.invalidateQueries({ queryKey: CONTAINERS_KEY }),
  });

  const stopMutation = useMutation({
    mutationFn: (containerId: string) => containersApi.stop(containerId),
    onSuccess: () => qc.invalidateQueries({ queryKey: CONTAINERS_KEY }),
  });

  return {
    containers: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    runMutation,
    stopMutation,
  };
}
