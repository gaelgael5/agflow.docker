// frontend/src/hooks/useGroupAvailableVars.ts
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { secretsApi } from "@/lib/secretsApi";
import { groupVariablesApi } from "@/lib/groupVariablesApi";
import { groupScriptsApi, scriptsApi } from "@/lib/scriptsApi";
import type { VarSources } from "@/lib/missingVars";

/**
 * Retourne les trois ensembles de noms de variables disponibles pour un groupe.
 *
 * @param groupId   ID du groupe
 * @param upToPosition  Si fourni, ne prend que les scripts before dont position < upToPosition.
 *                      Si absent, prend tous les scripts before (usage instances).
 */
export function useGroupAvailableVars(
  groupId: string,
  upToPosition?: number,
): VarSources {
  const secretsQuery = useQuery({
    queryKey: ["secrets"],
    queryFn: () => secretsApi.list(),
  });
  const groupVarsQuery = useQuery({
    queryKey: ["group-variables", groupId],
    queryFn: () => groupVariablesApi.list(groupId),
  });
  const groupScriptsQuery = useQuery({
    queryKey: ["group-scripts", groupId],
    queryFn: () => groupScriptsApi.list(groupId),
  });
  const allScriptsQuery = useQuery({
    queryKey: ["scripts"],
    queryFn: () => scriptsApi.list(),
  });

  return useMemo(() => {
    const globalVarNames = new Set<string>(
      (secretsQuery.data ?? [])
        .filter((s) => s.has_value)
        .map((s) => s.name),
    );

    const groupVarNames = new Set<string>(
      (groupVarsQuery.data ?? [])
        .filter((v) => v.value.trim() !== "")
        .map((v) => v.name),
    );

    const allScriptsById = new Map(
      (allScriptsQuery.data ?? []).map((s) => [s.id, s]),
    );

    const beforeScripts = (groupScriptsQuery.data ?? []).filter(
      (gs) =>
        gs.timing === "before" &&
        (upToPosition === undefined || gs.position < upToPosition),
    );

    const beforeOutputNames = new Set<string>(
      beforeScripts.flatMap((gs) => {
        const script = allScriptsById.get(gs.script_id);
        return (script?.output_variables ?? []).map((ov) => ov.name);
      }),
    );

    return { globalVarNames, groupVarNames, beforeOutputNames };
  }, [
    secretsQuery.data,
    groupVarsQuery.data,
    groupScriptsQuery.data,
    allScriptsQuery.data,
    upToPosition,
  ]);
}
