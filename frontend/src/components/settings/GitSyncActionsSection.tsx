import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { useRunExport } from "@/hooks/useGitSync";
import { GitSyncPreviewDialog } from "./GitSyncPreviewDialog";
import { type GitSyncConfig } from "@/lib/gitSyncApi";

type Props = { config: GitSyncConfig };

function extractErrorMessage(err: unknown): string {
  const resp = (err as { response?: { data?: { detail?: unknown } } }).response;
  const detail = resp?.data?.detail;
  if (typeof detail === "string") return detail;
  const msg = (err as { message?: string }).message;
  return msg ?? "Unknown error";
}

function fmtDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

export function GitSyncActionsSection({ config }: Props) {
  const { t } = useTranslation();
  const exp = useRunExport();
  const [previewOpen, setPreviewOpen] = useState(false);

  const handleExport = async () => {
    try {
      const r = await exp.mutateAsync();
      toast.success(
        t("settings.gitSync.toast.exportSuccess", {
          sha: r.sha.slice(0, 7),
          count: r.tables_count,
        }),
      );
    } catch (e) {
      toast.error(
        t("settings.gitSync.toast.exportFailed", {
          error: extractErrorMessage(e),
        }),
      );
    }
  };

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t("settings.gitSync.actions.title")}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button onClick={handleExport} disabled={exp.isPending}>
            {t("settings.gitSync.actions.exportNow")}
          </Button>
          <Button variant="outline" onClick={() => setPreviewOpen(true)}>
            {t("settings.gitSync.actions.previewImport")}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t("settings.gitSync.lastExport.title")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1.5 text-[13px]">
          {config.last_export_at === null ? (
            <p className="text-muted-foreground">
              {t("settings.gitSync.lastExport.never")}
            </p>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <Badge
                  className={
                    config.last_export_status === "ok"
                      ? "bg-green-600 hover:bg-green-600"
                      : "bg-destructive hover:bg-destructive"
                  }
                >
                  {config.last_export_status
                    ? t(
                        `settings.gitSync.lastExport.${config.last_export_status}`,
                      )
                    : "—"}
                </Badge>
                <span className="text-muted-foreground">
                  {fmtDate(config.last_export_at)}
                </span>
              </div>
              {config.last_export_sha && (
                <div>
                  <span className="text-muted-foreground">
                    {t("settings.gitSync.lastExport.sha")} :{" "}
                  </span>
                  <code className="text-xs">
                    {config.last_export_sha.slice(0, 7)}
                  </code>
                </div>
              )}
              {config.last_export_tables_count !== null && (
                <div>
                  {t("settings.gitSync.lastExport.tablesCount", {
                    count: config.last_export_tables_count,
                  })}
                </div>
              )}
              {config.last_export_error && (
                <p className="text-xs text-destructive font-mono break-all">
                  {config.last_export_error}
                </p>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t("settings.gitSync.lastImport.title")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1.5 text-[13px]">
          {config.last_import_at === null ? (
            <p className="text-muted-foreground">
              {t("settings.gitSync.lastImport.never")}
            </p>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <Badge
                  className={
                    config.last_import_status === "ok"
                      ? "bg-green-600 hover:bg-green-600"
                      : "bg-destructive hover:bg-destructive"
                  }
                >
                  {config.last_import_status
                    ? t(
                        `settings.gitSync.lastImport.${config.last_import_status}`,
                      )
                    : "—"}
                </Badge>
                <span className="text-muted-foreground">
                  {fmtDate(config.last_import_at)}
                </span>
              </div>
              {config.last_import_status === "ok" && (
                <div className="flex gap-3 text-xs">
                  <span>
                    {t("settings.gitSync.lastImport.inserted")} :{" "}
                    {config.last_import_rows_inserted ?? 0}
                  </span>
                  <span>
                    {t("settings.gitSync.lastImport.updated")} :{" "}
                    {config.last_import_rows_updated ?? 0}
                  </span>
                  <span>
                    {t("settings.gitSync.lastImport.deleted")} :{" "}
                    {config.last_import_rows_deleted ?? 0}
                  </span>
                </div>
              )}
              {config.last_import_error && (
                <p className="text-xs text-destructive font-mono break-all">
                  {config.last_import_error}
                </p>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <GitSyncPreviewDialog
        open={previewOpen}
        onOpenChange={setPreviewOpen}
      />
    </>
  );
}
