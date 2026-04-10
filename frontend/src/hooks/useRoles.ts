import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  rolesApi,
  type RoleCreate,
  type RoleSummary,
  type RoleUpdate,
} from "@/lib/rolesApi";

const ROLES_KEY = ["roles"] as const;

export function useRoles() {
  const qc = useQueryClient();

  const listQuery = useQuery<RoleSummary[]>({
    queryKey: ROLES_KEY,
    queryFn: () => rolesApi.list(),
  });

  const invalidateAll = (id?: string) => {
    qc.invalidateQueries({ queryKey: ROLES_KEY });
    if (id) qc.invalidateQueries({ queryKey: ["role", id] });
  };

  const createMutation = useMutation({
    mutationFn: (payload: RoleCreate) => rolesApi.create(payload),
    onSuccess: (data) => invalidateAll(data.id),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: RoleUpdate }) =>
      rolesApi.update(id, payload),
    onSuccess: (_data, variables) => invalidateAll(variables.id),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => rolesApi.remove(id),
    onSuccess: (_data, id) => invalidateAll(id),
  });

  const generateMutation = useMutation({
    mutationFn: (id: string) => rolesApi.generatePrompts(id),
    onSuccess: (_data, id) => invalidateAll(id),
  });

  return {
    roles: listQuery.data,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    createMutation,
    updateMutation,
    deleteMutation,
    generateMutation,
  };
}
