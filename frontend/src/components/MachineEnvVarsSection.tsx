import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useMachineEnvVars, useMachineEnvVarsUpsert } from "@/hooks/useInfraEnvVars";
import { StatusIndicator, type IndicatorStatus } from "@/components/StatusIndicator";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function valueStatus(value: string): IndicatorStatus {
  if (!value) return "missing";
  if (value.includes("${")) return "empty";
  return "ok";
}

export function MachineEnvVarsSection({ machineId }: { machineId: string }) {
  const { t } = useTranslation();
  const { data: envVars = [], isLoading } = useMachineEnvVars(machineId);
  const upsert = useMachineEnvVarsUpsert(machineId);
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    if (envVars.length > 0) {
      const initial: Record<string, string> = {};
      for (const ev of envVars) initial[ev.named_type_env_var_id] = ev.value;
      setValues(initial);
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
    try {
      await upsert.mutateAsync({ values });
      toast.success(t("infra.machine_env_vars_saved"));
    } catch {
      toast.error(t("infra.machine_env_vars_save_error"));
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">{t("infra.machine_env_vars_title")}</p>
      <div className="space-y-2">
        {envVars.map((ev) => {
          const val = values[ev.named_type_env_var_id] ?? ev.value;
          return (
            <div key={ev.id} className="grid grid-cols-[auto_1fr_24px] gap-2 items-center">
              <div className="min-w-0">
                <p className="text-xs font-mono font-medium">{ev.name}</p>
                {ev.description && (
                  <p className="text-[10px] text-muted-foreground">{ev.description}</p>
                )}
              </div>
              <Input
                className="h-7 text-xs font-mono"
                placeholder={t("infra.machine_env_var_value_placeholder")}
                value={val}
                onChange={(e) =>
                  setValues({ ...values, [ev.named_type_env_var_id]: e.target.value })
                }
              />
              <StatusIndicator status={valueStatus(val)} label={ev.name} />
            </div>
          );
        })}
      </div>
      <Button size="sm" onClick={() => void handleSave()} disabled={upsert.isPending}>
        {upsert.isPending ? "…" : t("infra.machine_env_vars_save_button")}
      </Button>
    </div>
  );
}
