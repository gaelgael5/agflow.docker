import { useTranslation } from "react-i18next";

import { usePitrActiveClone } from "@/hooks/usePitr";
import { Button } from "@/components/ui/button";

function formatDuration(sec: number): string {
  if (sec <= 0) return "0m";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return `${h}h ${m}m`;
}

function statusDot(status: string): string {
  if (status === "ready") return "🟢";
  if (status === "restoring") return "🟡";
  if (status === "terminating") return "🟠";
  if (status === "failed") return "🔴";
  return "⚪";
}

export function ActiveCloneCard() {
  const { t, i18n } = useTranslation();
  const { data, extend, terminate } = usePitrActiveClone();

  const onExtend = () => extend.mutate();
  const onStop = () => terminate.mutate();

  if (!data || data.status === "terminated") {
    return (
      <div className="text-sm text-muted-foreground">
        {t("backups.pitr.clone.none")}
      </div>
    );
  }

  return (
    <div className="space-y-2 rounded border p-3">
      <div className="text-sm">
        {statusDot(data.status)} <span className="font-medium">{t(`backups.pitr.clone.${data.status}`)}</span>
        {data.status === "ready" && (
          <>
            {" — "}
            {t("backups.pitr.clone.targetedAt")}{" "}
            {new Date(data.target_time).toLocaleString(i18n.language)}
          </>
        )}
      </div>
      {data.error && (
        <div className="text-xs text-destructive">{data.error}</div>
      )}
      <div className="text-xs text-muted-foreground">
        {t("backups.pitr.clone.expiresIn", { duration: formatDuration(data.expires_in_seconds) })}
      </div>
      <div className="flex flex-wrap gap-2">
        {data.pgweb_url && (
          <a href={data.pgweb_url} target="_blank" rel="noreferrer">
            <Button variant="secondary" size="sm">
              {t("backups.pitr.clone.openPgweb")} ↗
            </Button>
          </a>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={onExtend}
          disabled={extend.isPending || data.status !== "ready"}
        >
          {t("backups.pitr.clone.extendButton")}
        </Button>
        <Button
          variant="destructive"
          size="sm"
          onClick={onStop}
          disabled={terminate.isPending}
        >
          {t("backups.pitr.clone.stopButton")}
        </Button>
      </div>
    </div>
  );
}
