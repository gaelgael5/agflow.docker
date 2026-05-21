import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  machineEnvVarsApi,
  namedTypeEnvVarsApi,
  projectEnvVarsApi,
  type MachineEnvVarUpsert,
  type NamedTypeEnvVarCreate,
  type NamedTypeEnvVarUpdate,
} from "@/lib/infraEnvVarsApi";

export function useNamedTypeEnvVars(namedTypeId: string | null | undefined) {
  return useQuery({
    queryKey: ["infra-nt-env-vars", namedTypeId ?? ""],
    queryFn: () => namedTypeEnvVarsApi.list(namedTypeId as string),
    enabled: !!namedTypeId,
  });
}

export function useNamedTypeEnvVarsMutations(namedTypeId: string) {
  const qc = useQueryClient();
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["infra-nt-env-vars", namedTypeId] });

  const create = useMutation({
    mutationFn: (p: NamedTypeEnvVarCreate) => namedTypeEnvVarsApi.create(namedTypeId, p),
    onSuccess: invalidate,
  });
  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: NamedTypeEnvVarUpdate }) =>
      namedTypeEnvVarsApi.update(namedTypeId, id, payload),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => namedTypeEnvVarsApi.remove(namedTypeId, id),
    onSuccess: invalidate,
  });

  return { create, update, remove };
}

export function useMachineEnvVars(machineId: string | null | undefined) {
  return useQuery({
    queryKey: ["infra-machine-env-vars", machineId ?? ""],
    queryFn: () => machineEnvVarsApi.list(machineId as string),
    enabled: !!machineId,
  });
}

export function useMachineEnvVarsUpsert(machineId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: MachineEnvVarUpsert) => machineEnvVarsApi.upsert(machineId, payload),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["infra-machine-env-vars", machineId] }),
  });
}

export function useProjectEnvVarsCheck(projectId: string | null | undefined) {
  return useQuery({
    queryKey: ["project-env-vars-check", projectId ?? ""],
    queryFn: () => projectEnvVarsApi.check(projectId as string),
    enabled: !!projectId,
  });
}
