import { useTranslation } from "react-i18next";

import { type BasebackupPushSummary } from "@/lib/pitrApi";
import { usePitrBasebackups } from "@/hooks/usePitr";
import { Button } from "@/components/ui/button";

import { BasebackupActionsMenu } from "./BasebackupActionsMenu";

function formatSize(n: number | null): string {
  if (n == null) return "—";
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(0)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

function pushBadge(p: BasebackupPushSummary): string {
  if (p.status === "ok") return "✓";
  if (p.status === "failed") return "✗";
  if (p.status === "pushing") return "⏳";
  return "…";
}

export function BasebackupsList() {
  const { t, i18n } = useTranslation();
  const { data, isLoading, trigger } = usePitrBasebackups();

  const onTriggerNow = () => {
    trigger.mutate();
  };

  if (isLoading) {
    return <div className="text-sm text-muted-foreground">…</div>;
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">{t("backups.pitr.basebackups.title")}</h3>
        <Button size="sm" onClick={onTriggerNow} disabled={trigger.isPending}>
          {t("backups.pitr.basebackups.triggerNow")}
        </Button>
      </div>
      {!data || data.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t("backups.pitr.basebackups.empty")}
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="pb-1">{t("backups.pitr.basebackups.colDate")}</th>
              <th className="pb-1">{t("backups.pitr.basebackups.colSize")}</th>
              <th className="pb-1">{t("backups.pitr.basebackups.colPushes")}</th>
              <th className="pb-1 text-right">{t("backups.pitr.basebackups.colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((b) => (
              <tr key={b.id} className="border-t">
                <td className="py-1">
                  {new Date(b.started_at).toLocaleString(i18n.language)}
                </td>
                <td className="py-1">{formatSize(b.size_bytes)}</td>
                <td className="space-x-2 py-1">
                  {b.pushes.length === 0 ? (
                    <span className="text-muted-foreground">—</span>
                  ) : (
                    b.pushes.map((p) => (
                      <span
                        key={p.remote_connection_id}
                        title={p.error ?? p.status}
                      >
                        {pushBadge(p)} {p.remote_connection_name}
                      </span>
                    ))
                  )}
                </td>
                <td className="py-1 text-right">
                  <BasebackupActionsMenu basebackup={b} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
