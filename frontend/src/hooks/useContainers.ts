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
    mutationFn: ({
      dockerfileId,
      secrets,
    }: {
      dockerfileId: string;
      secrets?: Record<string, string>;
    }) => containersApi.run(dockerfileId, secrets),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: CONTAINERS_KEY });
      // Container start auto-creates mount dirs (workspace/, etc.) — refresh
      // the dockerfile detail so the file tree picks them up.
      qc.invalidateQueries({ queryKey: ["dockerfile", variables.dockerfileId] });
    },
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
