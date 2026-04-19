import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { projectsApi, type ProjectCreatePayload } from "@/lib/projectsApi";

const KEY = ["projects"] as const;

export function useProjects() {
  const qc = useQueryClient();

  const listQuery = useQuery({
    queryKey: KEY,
    queryFn: () => projectsApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (p: ProjectCreatePayload) => projectsApi.create(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => projectsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });

  return {
    projects: listQuery.data,
    isLoading: listQuery.isLoading,
    createMutation,
    deleteMutation,
  };
}
