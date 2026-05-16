import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useLocalBackups, useRestoreMutation } from "@/hooks/useBackups";
import type { LocalBackup } from "@/lib/backupsApi";

import { RestoreConfirmDialog } from "./RestoreConfirmDialog";

function formatSize(bytes: number | null): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

export function LocalBackupsSection() {
  const { t } = useTranslation();
  const { data: backups, isLoading, error } = useLocalBackups();
  const restore = useRestoreMutation();
  const [restoreTarget, setRestoreTarget] = useState<LocalBackup | null>(null);
  const [sourceFilter, setSourceFilter] = useState<
    "all" | "manual" | "full" | "snapshot"
  >("all");

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>;
  }
  if (error) {
    return (
      <p className="text-sm text-destructive">{t("common.error_loading")}</p>
    );
  }

  const filtered =
    sourceFilter === "all"
      ? (backups ?? [])
      : (backups ?? []).filter((b) => b.source_kind === sourceFilter);

  const hasBackups = backups && backups.length > 0;

  return (
    <section className="space-y-4">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold">{t("backups.local.title")}</h2>
        <p className="text-sm text-muted-foreground">
          {t("backups.local.subtitle")}
        </p>
      </header>

      <div className="flex items-center gap-2">
        <Label htmlFor="local-backups-filter">
          {t("backups.filterSource")}
        </Label>
        <select
          id="local-backups-filter"
          value={sourceFilter}
          onChange={(e) =>
            setSourceFilter(e.target.value as typeof sourceFilter)
          }
          className="text-sm border rounded px-2 py-1 bg-background"
        >
          <option value="all">{t("backups.filterAll")}</option>
          <option value="manual">{t("backups.filterManual")}</option>
          <option value="full">{t("backups.filterFull")}</option>
          <option value="snapshot">{t("backups.filterSnapshot")}</option>
        </select>
      </div>

      {!hasBackups ? (
        <p className="text-sm text-muted-foreground">
          {t("backups.local.empty")}
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("backups.local.filename")}</TableHead>
              <TableHead>{t("backups.local.size")}</TableHead>
              <TableHead>{t("backups.local.status")}</TableHead>
              <TableHead>{t("backups.local.source")}</TableHead>
              <TableHead>{t("backups.local.created_at")}</TableHead>
              <TableHead className="text-right">
                {t("backups.local.actions")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((b) => (
              <TableRow key={b.id}>
                <TableCell className="font-mono text-xs">{b.filename}</TableCell>
                <TableCell>{formatSize(b.size_bytes)}</TableCell>
                <TableCell>{b.status}</TableCell>
                <TableCell>
                  {b.source_remote_connection_id
                    ? t("backups.local.source_remote", { name: "—" })
                    : t("backups.local.source_local")}
                </TableCell>
                <TableCell>
                  {new Date(b.created_at).toLocaleString()}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => setRestoreTarget(b)}
                    disabled={b.status !== "completed"}
                  >
                    {t("backups.local.restore")}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {restoreTarget && (
        <RestoreConfirmDialog
          open={true}
          filename={restoreTarget.filename}
          isLoading={restore.isPending}
          onCancel={() => setRestoreTarget(null)}
          onConfirm={(fname) => {
            restore.mutate(
              { backupId: restoreTarget.id, filename: fname },
              {
                onSuccess: (result) => {
                  setRestoreTarget(null);
                  toast.success(
                    t("backups.restore.success", { code: result.exit_code }),
                  );
                },
                onError: (err) => {
                  toast.error(
                    t("backups.restore.error", { message: err.message }),
                  );
                },
              },
            );
          }}
        />
      )}
    </section>
  );
}
