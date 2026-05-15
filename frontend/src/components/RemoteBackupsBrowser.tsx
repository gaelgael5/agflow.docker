import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import type { Connection } from "@/components/backup-remotes/types";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useRemoteFiles, usePullMutation } from "@/hooks/useBackups";
import { api } from "@/lib/api";

function formatSize(bytes: number | null): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

export function RemoteBackupsBrowser() {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const pull = usePullMutation();

  const { data: connections = [] } = useQuery<Connection[]>({
    queryKey: ["backup-remotes"],
    queryFn: () =>
      api.get<Connection[]>("/admin/backup-remotes").then((r) => r.data),
  });

  const { data: files, isLoading, error } = useRemoteFiles(selectedId);

  return (
    <section className="space-y-4">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold">{t("backups.remote.title")}</h2>
        <p className="text-sm text-muted-foreground">
          {t("backups.remote.subtitle")}
        </p>
      </header>

      <div className="max-w-md space-y-2">
        <label htmlFor="remote-selector" className="text-sm font-medium">
          {t("backups.remote.select_connection")}
        </label>
        <Select
          value={selectedId ?? ""}
          onValueChange={(v) => setSelectedId(v || null)}
        >
          <SelectTrigger id="remote-selector">
            <SelectValue placeholder={t("backups.remote.select_connection")} />
          </SelectTrigger>
          <SelectContent>
            {connections.map((c) => (
              <SelectItem key={c.id} value={c.id}>
                {c.name} ({c.kind})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {!selectedId ? (
        <p className="text-sm text-muted-foreground">
          {t("backups.remote.no_connection")}
        </p>
      ) : isLoading ? (
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      ) : error ? (
        <p className="text-sm text-destructive">
          {t("backups.remote.load_error")} :{" "}
          {(error as Error).message}
        </p>
      ) : !files || files.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t("backups.remote.empty")}
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("backups.remote.filename")}</TableHead>
              <TableHead>{t("backups.remote.size")}</TableHead>
              <TableHead>{t("backups.remote.last_modified")}</TableHead>
              <TableHead className="text-right">
                {t("backups.local.actions")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {files.map((f) => (
              <TableRow key={f.filename}>
                <TableCell className="font-mono text-xs">
                  {f.filename}
                </TableCell>
                <TableCell>{formatSize(f.size_bytes)}</TableCell>
                <TableCell>
                  {f.last_modified
                    ? new Date(f.last_modified).toLocaleString()
                    : "—"}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    size="sm"
                    onClick={() =>
                      pull.mutate(
                        { connectionId: selectedId, filename: f.filename },
                        {
                          onSuccess: () =>
                            toast.success(
                              t("backups.pull.success", {
                                filename: f.filename,
                              }),
                            ),
                          onError: (err) =>
                            toast.error(
                              t("backups.pull.error", {
                                message: err.message,
                              }),
                            ),
                        },
                      )
                    }
                    disabled={pull.isPending}
                  >
                    {t("backups.remote.pull")}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}
