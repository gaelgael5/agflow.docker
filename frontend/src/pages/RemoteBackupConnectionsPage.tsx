import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { runGDriveReauthorize } from "@/lib/gdriveOAuth";
import {
  ConnectionModal,
  type Connection,
} from "@/components/backup-remotes/ConnectionModal";

// ─── Page ────────────────────────────────────────────────────────────────────

export function RemoteBackupConnectionsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [modalConn, setModalConn] = useState<Connection | null | "new">(null);
  const [deleteTarget, setDeleteTarget] = useState<Connection | null>(null);

  const { data: connections = [], isLoading, isError } = useQuery<Connection[]>({
    queryKey: ["backup-remotes"],
    queryFn: () =>
      api
        .get<Connection[]>("/admin/backup-remotes")
        .then((r) => r.data),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/admin/backup-remotes/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["backup-remotes"] });
    },
  });

  if (isLoading) {
    return (
      <p className="p-6 text-sm text-muted-foreground">{t("common.loading")}</p>
    );
  }

  if (isError) {
    return (
      <p className="p-6 text-sm text-destructive">{t("common.error_loading")}</p>
    );
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold">{t("backup_remotes.title")}</h1>
        <Button onClick={() => setModalConn("new")}>
          {t("backup_remotes.add")}
        </Button>
      </div>

      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="py-2 pr-4">{t("backup_remotes.name")}</th>
            <th className="pr-4">{t("backup_remotes.kind")}</th>
            <th className="pr-4">{t("backup_remotes.host")}</th>
            <th className="pr-4">{t("backup_remotes.paths")}</th>
            <th>{t("backup_remotes.has_credentials")}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {connections.map((c) => (
            <tr
              key={c.id}
              className="border-b hover:bg-muted/50 cursor-pointer"
              onClick={() => setModalConn(c)}
            >
              <td className="py-2 pr-4 font-medium">{c.name}</td>
              <td className="pr-4 uppercase text-xs">{c.kind}</td>
              <td className="pr-4">
                {c.kind === "gdrive" ? (
                  <span className="text-xs">
                    {c.config["user_email"] ?? "—"}
                    {" · "}
                    {c.config["folder_name"] ?? "—"}
                  </span>
                ) : (
                  <span>
                    {c.config["host"] ?? "—"}
                  </span>
                )}
              </td>
              <td className="pr-4 text-xs text-muted-foreground">
                {[
                  c.config["remote_path_full"],
                  c.config["prefix_full"],
                ]
                  .filter(Boolean)
                  .join(" / ") || t("backup_remotes.not_configured")}
              </td>
              <td>
                <span aria-hidden="true">{c.has_credentials ? "✓" : "✗"}</span>
              </td>
              <td className="flex items-center gap-1">
                {c.kind === "gdrive" && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={async (e) => {
                      e.stopPropagation();
                      try {
                        await runGDriveReauthorize(c.id);
                        toast.success(t("backups.gdrive.phaseConfirmedTitle"));
                      } catch (err) {
                        toast.error(String(err));
                      }
                    }}
                  >
                    {t("backups.gdrive.btnReauthorize")}
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={t("backup_remotes.delete_aria")}
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeleteTarget(c);
                  }}
                >
                  ×
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {modalConn !== null && (
        <ConnectionModal
          key={modalConn === "new" ? "new" : (modalConn as Connection).id}
          connection={modalConn === "new" ? null : modalConn}
          onClose={() => setModalConn(null)}
          onSaved={() => setModalConn(null)}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title={t("backup_remotes.delete_confirm")}
        description={
          deleteTarget
            ? t("backup_remotes.delete_description", {
                name: deleteTarget.name,
              })
            : ""
        }
        destructive
        onConfirm={() => {
          if (deleteTarget) {
            deleteMutation.mutate(deleteTarget.id);
          }
        }}
      />
    </div>
  );
}
