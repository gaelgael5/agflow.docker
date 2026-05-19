import { useTranslation } from "react-i18next";

import { usePitrWalStatus } from "@/hooks/usePitr";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

export function WalArchiveStatus() {
  const { t, i18n } = useTranslation();
  const { data, isLoading } = usePitrWalStatus();
  if (isLoading || !data) {
    return <div className="text-sm text-muted-foreground">…</div>;
  }

  const dot = data.archiving_enabled ? "🟢" : "🔴";
  const lastFmt = data.last_archived_at
    ? new Date(data.last_archived_at).toLocaleString(i18n.language)
    : t("backups.pitr.wal.never");

  return (
    <div className="space-y-1 text-sm">
      <div>
        {dot}{" "}
        {data.archiving_enabled
          ? t("backups.pitr.wal.archivingActive")
          : t("backups.pitr.wal.archivingInactive")}
        {data.archive_lag_seconds !== null && (
          <span className="text-muted-foreground">
            {" "}
            · {t("backups.pitr.wal.lastArchived")} {lastFmt} (lag {data.archive_lag_seconds}s)
          </span>
        )}
      </div>
      <div className="text-muted-foreground">
        {t("backups.pitr.wal.diskUsage", {
          used: formatBytes(data.wal_disk_used_bytes),
          free: formatBytes(data.wal_disk_free_bytes),
        })}
      </div>
    </div>
  );
}
