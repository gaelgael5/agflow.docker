import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Lock, LockOpen } from "lucide-react";
import { toast } from "sonner";
import { useMachineEnvVars, useMachineEnvVarsUpsert } from "@/hooks/useInfraEnvVars";
import { useHarpocrateVaults } from "@/hooks/useHarpocrateVaults";
import { StatusIndicator, type IndicatorStatus } from "@/components/StatusIndicator";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { MachineEnvVar, MachineSecretEntry } from "@/lib/infraEnvVarsApi";

function valueStatus(ev: MachineEnvVar, localValue: string): IndicatorStatus {
  if (ev.is_secret) {
    if (localValue) return "ok";
    if (ev.value.startsWith("${vault://")) return "ok";
    return "missing";
  }
  return localValue ? "ok" : "missing";
}

export function MachineEnvVarsSection({ machineId }: { machineId: string }) {
  const { t } = useTranslation();
  const { data: envVars = [], isLoading } = useMachineEnvVars(machineId);
  const upsert = useMachineEnvVarsUpsert(machineId);
  const { vaults, defaultVault } = useHarpocrateVaults();
  const [localValues, setLocalValues] = useState<Record<string, string>>({});
  const [vaultName, setVaultName] = useState("");

  const effectiveVaultName = vaultName || defaultVault?.name || vaults[0]?.name || "";
  const hasSecretVars = envVars.some((ev) => ev.is_secret);

  useEffect(() => {
    if (envVars.length > 0) {
      const initial: Record<string, string> = {};
      for (const ev of envVars) {
        initial[ev.named_type_env_var_id] = ev.is_secret ? "" : ev.value;
      }
      setLocalValues(initial);
    }
  }, [envVars]);

  if (isLoading) return <p className="text-xs text-muted-foreground">…</p>;

  if (envVars.length === 0) {
    return (
      <p className="text-xs text-muted-foreground italic">
        {t("infra.machine_env_vars_empty")}
      </p>
    );
  }

  async function handleSave() {
    const values: Record<string, string> = {};
    const secrets: Record<string, MachineSecretEntry> = {};

    for (const ev of envVars) {
      const val = localValues[ev.named_type_env_var_id] ?? "";
      if (ev.is_secret) {
        if (val) {
          secrets[ev.named_type_env_var_id] = { vault_name: effectiveVaultName, value: val };
        }
      } else {
        values[ev.named_type_env_var_id] = val;
      }
    }

    try {
      await upsert.mutateAsync({ values, secrets });
      toast.success(t("infra.machine_env_vars_saved"));
      setLocalValues((prev) => {
        const next = { ...prev };
        for (const ev of envVars) {
          if (ev.is_secret) next[ev.named_type_env_var_id] = "";
        }
        return next;
      });
    } catch {
      toast.error(t("infra.machine_env_vars_save_error"));
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">{t("infra.machine_env_vars_title")}</p>

      {hasSecretVars && vaults.length > 0 && (
        <div>
          <p className="text-[11px] text-muted-foreground mb-1">
            {t("infra.machine_env_var_vault_label")}
          </p>
          <select
            value={vaultName}
            onChange={(e) => setVaultName(e.target.value)}
            className="flex h-8 w-full rounded-md border border-input bg-background px-3 py-1 text-xs shadow-sm"
          >
            {vaults.map((v) => (
              <option key={v.id} value={v.name}>
                {v.name}{v.is_default ? ` (${t("infra.machine_env_var_vault_default")})` : ""}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="space-y-3">
        {envVars.map((ev) => {
          const val = localValues[ev.named_type_env_var_id] ?? "";
          const vaultPath = `\${vault://${effectiveVaultName}:env-vars/${machineId}/${ev.named_type_env_var_id}}`;
          return (
            <div key={ev.id}>
              <div className="grid grid-cols-[minmax(6rem,9rem)_1fr_24px] gap-2 items-start">
                <div className="mt-1.5 min-w-0">
                  <div className="flex items-center gap-1">
                    <p className="text-xs font-mono font-medium truncate">{ev.name}</p>
                    {ev.is_secret
                      ? <Lock className="w-3 h-3 shrink-0 text-amber-500" />
                      : <LockOpen className="w-3 h-3 shrink-0 text-muted-foreground/40" />}
                  </div>
                  {ev.description && (
                    <p className="text-[10px] text-muted-foreground truncate">{ev.description}</p>
                  )}
                </div>
                <div>
                  <Input
                    type={ev.is_secret ? "password" : "text"}
                    className="h-7 text-xs font-mono"
                    placeholder={
                      ev.is_secret
                        ? t("infra.machine_env_var_secret_placeholder")
                        : t("infra.machine_env_var_value_placeholder")
                    }
                    value={val}
                    onChange={(e) =>
                      setLocalValues({ ...localValues, [ev.named_type_env_var_id]: e.target.value })
                    }
                  />
                  {ev.is_secret && (
                    <p className="mt-0.5 text-[10px] text-muted-foreground font-mono break-all">
                      {vaultPath}
                    </p>
                  )}
                </div>
                <div className="mt-1.5">
                  <StatusIndicator status={valueStatus(ev, val)} label={ev.name} />
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <Button size="sm" onClick={() => void handleSave()} disabled={upsert.isPending}>
        {upsert.isPending ? t("common.saving") : t("infra.machine_env_vars_save_button")}
      </Button>
    </div>
  );
}
