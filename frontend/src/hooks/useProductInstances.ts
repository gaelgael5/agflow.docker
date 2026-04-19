import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { productInstancesApi, type InstanceCreatePayload } from "@/lib/productInstancesApi";

const KEY = ["product-instances"] as const;

export function useProductInstances(projectId?: string) {
  const qc = useQueryClient();

  const listQuery = useQuery({
    queryKey: projectId ? [...KEY, projectId] : KEY,
    queryFn: () => productInstancesApi.list(projectId),
  });

  const createMutation = useMutation({
    mutationFn: (p: InstanceCreatePayload) => productInstancesApi.create(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: ({ projectId: pid, instanceId }: { projectId: string; instanceId: string }) =>
      productInstancesApi.remove(pid, instanceId),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  const activateMutation = useMutation({
    mutationFn: ({ projectId: pid, instanceId, serviceUrl }: { projectId: string; instanceId: string; serviceUrl: string }) =>
      productInstancesApi.activate(pid, instanceId, serviceUrl),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  const stopMutation = useMutation({
    mutationFn: ({ projectId: pid, instanceId }: { projectId: string; instanceId: string }) =>
      productInstancesApi.stop(pid, instanceId),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  return {
    instances: listQuery.data,
    isLoading: listQuery.isLoading,
    createMutation,
    deleteMutation,
    activateMutation,
    stopMutation,
  };
}
