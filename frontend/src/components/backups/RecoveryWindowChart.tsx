import { useTranslation } from "react-i18next";

export interface RecoveryWindowChartProps {
  earliest: string | null;
  latest: string | null;
}

export function RecoveryWindowChart({ earliest, latest }: RecoveryWindowChartProps) {
  const { t, i18n } = useTranslation();

  if (!earliest || !latest) {
    return (
      <div className="text-sm text-muted-foreground">
        {t("backups.pitr.window.empty")}
      </div>
    );
  }

  const earliestFmt = new Date(earliest).toLocaleString(i18n.language);
  const latestFmt = new Date(latest).toLocaleString(i18n.language);

  return (
    <div className="space-y-1 text-sm">
      <div className="text-muted-foreground">{t("backups.pitr.window.title")}</div>
      <div className="font-mono text-xs">
        {earliestFmt}
        <span className="mx-2 text-muted-foreground">───────────</span>
        {latestFmt}
      </div>
    </div>
  );
}
