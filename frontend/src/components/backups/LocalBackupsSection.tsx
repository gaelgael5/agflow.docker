import type { JSX } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useLocalBackups, useRestoreMutation } from "@/hooks/useBackups";
import type { LocalBackup } from "@/lib/backupsApi";
import { localBackupPushesApi, type LocalBackupPush } from "@/lib/localBackupPushesApi";
import { api } from "@/lib/api";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function pushBadge(status: LocalBackupPush["status"]): string {
  if (status === "ok") return "✓";
  if (status === "failed") return "✗";
  if (status === "pushing") return "⏳";
  return "…"; // pending
}

// ─── PushesCell ───────────────────────────────────────────────────────────────

interface PushesCellProps {
  backup: LocalBackup;
  onRePush: (backupId: string, remoteId: string) => void;
}

function PushesCell({ backup, onRePush }: PushesCellProps): JSX.Element {
  const { t } = useTranslation();
  const hasFailed = backup.pushes.some((p) => p.status === "failed");

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {backup.pushes.length === 0 ? (
        <span className="text-muted-foreground">—</span>
      ) : (
        backup.pushes.map((p) => (
          <span
            key={p.remote_connection_id}
            title={p.error ?? p.status}
            className={p.status === "failed" ? "text-destructive" : ""}
          >
            {pushBadge(p.status)} {p.remote_connection_name}
          </span>
        ))
      )}
      {hasFailed && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" variant="ghost" className="h-5 px-1">
              ⋯
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            {backup.pushes
              .filter((p) => p.status === "failed")
              .map((p) => (
                <DropdownMenuItem
                  key={p.remote_connection_id}
                  onClick={() => onRePush(backup.id, p.remote_connection_id)}
                >
                  {t("backups.pushes.rePushAction", {
                    remote: p.remote_connection_name,
                  })}
                </DropdownMenuItem>
              ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function LocalBackupsSection(): JSX.Element {
  const { t } = useTranslation();
  const { data: backups = [], isLoading } = useLocalBackups();
  const qc = useQueryClient();
  const restoreMutation = useRestoreMutation();

  const [confirmDelete, setConfirmDelete] = useState<LocalBackup | null>(null);
  const [confirmRestore, setConfirmRestore] = useState<LocalBackup | null>(null);

  const pushMutation = useMutation({
    mutationFn: ({
      backupId,
      remoteId,
    }: {
      backupId: string;
      remoteId: string;
    }) => localBackupPushesApi.pushBackup(backupId, remoteId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["local-backups"] });
      toast.success(t("backups.pushes.rePushSuccess"));
    },
    onError: (err) =>
      toast.error(
        t("backups.pushes.rePushError", { error: (err as Error).message }),
      ),
  });

  const handleDelete = async () => {
    if (!confirmDelete) return;
    await api.delete(`/admin/local-backups/${confirmDelete.id}`);
    qc.invalidateQueries({ queryKey: ["local-backups"] });
    setConfirmDelete(null);
  };

  const handleRestore = async () => {
    if (!confirmRestore) return;
    await restoreMutation.mutateAsync({
      backupId: confirmRestore.id,
      filename: confirmRestore.filename,
    });
    toast.success(t("backups.restore.success"));
    setConfirmRestore(null);
  };

  function sourceLabel(b: LocalBackup): string {
    if (b.source_remote_connection_id) {
      return t("backups.local.source_remote", {
        name: b.source_remote_connection_id.slice(0, 8),
      });
    }
    return t("backups.local.source_local");
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("backups.local.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
        ) : backups.length === 0 ? (
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
                <TableHead>{t("backups.local.created_at")}</TableHead>
                <TableHead>{t("backups.local.source")}</TableHead>
                <TableHead>{t("backups.pushes.title")}</TableHead>
                <TableHead className="text-right">
                  {t("backups.local.actions")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {backups.map((b) => (
                <TableRow key={b.id}>
                  <TableCell className="font-mono text-xs">
                    {b.filename}
                    {!b.local_file_present && (
                      <span className="ml-2 text-xs text-muted-foreground italic">
                        ({t("backups.local.fileDeleted")})
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">
                    {formatBytes(b.size_bytes)}
                  </TableCell>
                  <TableCell className="text-xs">{b.status}</TableCell>
                  <TableCell className="text-xs">
                    {new Date(b.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-xs">{sourceLabel(b)}</TableCell>
                  <TableCell>
                    <PushesCell
                      backup={b}
                      onRePush={(backupId, remoteId) =>
                        pushMutation.mutate({ backupId, remoteId })
                      }
                    />
                  </TableCell>
                  <TableCell className="text-right space-x-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={!b.local_file_present}
                      onClick={() => setConfirmRestore(b)}
                      title={t("backups.local.restore")}
                    >
                      {t("backups.local.restore")}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setConfirmDelete(b)}
                      title={t("backups.local.delete")}
                      className="text-destructive"
                    >
                      {t("backups.local.delete")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <ConfirmDialog
        open={confirmDelete !== null}
        onOpenChange={(o) => !o && setConfirmDelete(null)}
        title={t("backups.local.delete")}
        description={t("backups.local.delete_confirm", {
          filename: confirmDelete?.filename ?? "",
        })}
        confirmLabel={t("backups.local.delete")}
        destructive
        onConfirm={handleDelete}
      />

      <ConfirmDialog
        open={confirmRestore !== null}
        onOpenChange={(o) => !o && setConfirmRestore(null)}
        title={t("backups.local.restore")}
        description={t("backups.restore.confirmDescription", {
          filename: confirmRestore?.filename ?? "",
        })}
        confirmLabel={t("backups.local.restore")}
        onConfirm={handleRestore}
      />
    </Card>
  );
}
