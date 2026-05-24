// frontend/src/hooks/useEnvMachineVarCheck.ts
import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { machineEnvVarsApi, type MachineEnvVar } from "@/lib/infraEnvVarsApi";
import type { MachineSummary } from "@/lib/infraApi";
import { parseEnvMachineRef } from "@/lib/missingVars";

export type EnvMachineStatus =
  | "ok"                // machine existe, variable existe et non vide
  | "machine_not_found" // machine inconnue dans la liste
  | "var_not_found"     // machine ok mais variable non déclarée
  | "var_empty";        // variable déclarée mais valeur vide

/**
 * Valide toutes les références ${env-machine://machine:var} présentes dans
 * inputValues contre la liste de machines connues et leurs variables d'env.
 *
 * Les placeholders littéraux <machine> sont ignorés (non validés).
 *
 * Retourne une Map<"machine:varName", EnvMachineStatus>.
 * Les clés absentes de la Map signifient "chargement en cours".
 */
export function useEnvMachineVarCheck(
  inputValues: Record<string, string>,
  machines: MachineSummary[],
): Map<string, EnvMachineStatus> {
  const refs = useMemo(() => {
    const seen = new Set<string>();
    const result: Array<{ machine: string; varName: string }> = [];
    for (const val of Object.values(inputValues)) {
      const ref = parseEnvMachineRef(val);
      if (ref && ref.machine !== "<machine>") {
        const key = `${ref.machine}:${ref.varName}`;
        if (!seen.has(key)) {
          seen.add(key);
          result.push(ref);
        }
      }
    }
    return result;
  }, [inputValues]);

  const machineByName = useMemo(
    () => new Map(machines.map((m) => [m.name, m])),
    [machines],
  );

  const referencedMachineIds = useMemo(() => {
    const ids = new Map<string, string>(); // machineName → machineId
    for (const ref of refs) {
      if (!ids.has(ref.machine)) {
        const m = machineByName.get(ref.machine);
        if (m) ids.set(ref.machine, m.id);
      }
    }
    return ids;
  }, [refs, machineByName]);

  const queries = useQueries({
    queries: [...referencedMachineIds.entries()].map(([machineName, machineId]) => ({
      queryKey: ["machine-env-vars", machineId],
      queryFn: async (): Promise<{ machineName: string; vars: MachineEnvVar[] }> => {
        const vars = await machineEnvVarsApi.list(machineId);
        return { machineName, vars };
      },
    })),
  });

  return useMemo(() => {
    const statusMap = new Map<string, EnvMachineStatus>();

    const envVarsByMachine = new Map<string, MachineEnvVar[]>();
    for (const q of queries) {
      if (q.data) {
        envVarsByMachine.set(q.data.machineName, q.data.vars);
      }
    }

    for (const ref of refs) {
      const key = `${ref.machine}:${ref.varName}`;
      const machineId = referencedMachineIds.get(ref.machine);

      if (!machineId) {
        statusMap.set(key, "machine_not_found");
        continue;
      }

      if (!envVarsByMachine.has(ref.machine)) {
        continue; // chargement en cours — pas de statut
      }

      const vars = envVarsByMachine.get(ref.machine)!;
      const envVar = vars.find((v) => v.name === ref.varName);

      if (!envVar) {
        statusMap.set(key, "var_not_found");
      } else if (!String(envVar.value ?? "").trim()) {
        statusMap.set(key, "var_empty");
      } else {
        statusMap.set(key, "ok");
      }
    }

    return statusMap;
  }, [refs, referencedMachineIds, queries]);
}
