import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { RestoreConfirmDialog } from "@/components/RestoreConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { backupsApi } from "@/lib/backupsApi";
import type { ScheduleHistoryEntry } from "@/lib/backupSchedulesApi";

interface Props {
  entries: ScheduleHistoryEntry[] | undefined;
  isLoading: boolean;
}

function formatSize(bytes: number | null): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function ScheduleHistoryTable({ entries, isLoading }: Props) {
  const { t } = useTranslation();
  const [restoreTarget, setRestoreTarget] = useState<ScheduleHistoryEntry | null>(null);

  const restoreMutation = useMutation({
    mutationFn: ({ id, filename }: { id: string; filename: string }) =>
      backupsApi.restoreLocal(id, filename),
    onSuccess: (res) => {
      toast.success(
        t("backups.restore.success", { exit_code: res.exit_code }),
      );
      setRestoreTarget(null);
    },
    onError: (err) => {
      toast.error(
        t("backups.restore.error", {
          msg: err instanceof Error ? err.message : String(err),
        }),
      );
    },
  });

  if (isLoading) {
    return <p className="text-xs text-muted-foreground p-2">{t("common.loading")}</p>;
  }
  if (!entries || entries.length === 0) {
    return (
      <p className="text-xs text-muted-foreground p-2">
        {t("backups.schedules.historyEmpty")}
      </p>
    );
  }

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("backups.schedules.historyColDate")}</TableHead>
            <TableHead>{t("backups.schedules.historyColStatus")}</TableHead>
            <TableHead>{t("backups.schedules.historyColSize")}</TableHead>
            <TableHead>{t("backups.schedules.historyColFilename")}</TableHead>
            <TableHead className="text-right">
              {t("backups.schedules.colActions")}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {entries.map((e) => (
            <TableRow key={e.id}>
              <TableCell className="text-xs">
                {new Date(e.created_at).toLocaleString()}
              </TableCell>
              <TableCell>
                <Badge
                  variant={
                    e.status === "completed"
                      ? "default"
                      : e.status === "failed"
                        ? "destructive"
                        : "secondary"
                  }
                >
                  {e.status}
                </Badge>
              </TableCell>
              <TableCell className="text-xs">{formatSize(e.size_bytes)}</TableCell>
              <TableCell className="text-xs font-mono break-all">{e.filename}</TableCell>
              <TableCell className="text-right">
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={e.status !== "completed"}
                  onClick={() => setRestoreTarget(e)}
                  title={t("backups.restore.button")}
                >
                  <RotateCcw className="h-4 w-4" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <RestoreConfirmDialog
        open={restoreTarget !== null}
        filename={restoreTarget?.filename ?? ""}
        isLoading={restoreMutation.isPending}
        onConfirm={(filename) => {
          if (restoreTarget) {
            restoreMutation.mutate({ id: restoreTarget.id, filename });
          }
        }}
        onCancel={() => setRestoreTarget(null)}
      />
    </>
  );
}
