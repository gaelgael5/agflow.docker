// frontend/src/components/projects/EnvVarsBanner.tsx
/**
 * Banniere d'alerte affichee sur ProjectDetailPage quand des variables
 * d'environnement ne peuvent pas etre resolues avant deploiement.
 *
 * Recoit les donnees du check deja chargees (pas de fetch interne)
 * afin de rester testable sans QueryClient.
 */
import { useTranslation } from "react-i18next";
import type { ProjectEnvVarsCheck } from "@/lib/infraEnvVarsApi";

interface EnvVarsBannerProps {
  check: ProjectEnvVarsCheck;
}

export function EnvVarsBanner({ check }: EnvVarsBannerProps) {
  const { t } = useTranslation();

  if (check.total_missing === 0) return null;

  return (
    <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm">
      <p className="font-medium text-destructive">
        {t("projects.env_vars_missing_banner", { count: check.total_missing })}
      </p>
      <ul className="mt-2 space-y-2">
        {check.items.map((item) => (
          <li key={item.group_script_id} className="text-xs">
            <div className="text-muted-foreground">
              <span className="font-mono">{item.script_name}</span>
              {" — "}
              <span>{item.group_name}</span>
            </div>
            <ul className="ml-4 mt-0.5 space-y-0.5">
              {item.missing.map((m) => (
                <li key={m.var_name} className="text-muted-foreground">
                  <span className="font-mono">{m.var_name}</span>
                  {" : "}
                  <span>
                    {t(`projects.env_vars_reason.${m.kind}`, { detail: m.detail })}
                  </span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}
