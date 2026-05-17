import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { GitSyncConfigDialog } from "./GitSyncConfigDialog";
import { useDeleteConfig } from "@/hooks/useGitSync";
import { type GitSyncConfig } from "@/lib/gitSyncApi";

type Props = { config: GitSyncConfig };

function extractErrorMessage(err: unknown): string {
  const resp = (err as { response?: { data?: { detail?: unknown } } }).response;
  const detail = resp?.data?.detail;
  if (typeof detail === "string") return detail;
  const msg = (err as { message?: string }).message;
  return msg ?? "Unknown error";
}

export function GitSyncConfigSection({ config }: Props) {
  const { t } = useTranslation();
  const [editOpen, setEditOpen] = useState(false);
  const [delOpen, setDelOpen] = useState(false);
  const del = useDeleteConfig();

  const handleDelete = async () => {
    try {
      await del.mutateAsync();
      toast.success(t("settings.gitSync.toast.configDeleted"));
    } catch (e) {
      toast.error(extractErrorMessage(e));
      throw e;
    }
  };

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">
            {t("settings.gitSync.config.title")}
          </CardTitle>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setEditOpen(true)}
            >
              {t("settings.gitSync.config.edit")}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setDelOpen(true)}
            >
              {t("settings.gitSync.config.delete")}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 text-[13px]">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground min-w-[140px]">
              {t("settings.gitSync.config.repoUrl")} :
            </span>
            <a
              href={config.repo_url}
              target="_blank"
              rel="noreferrer noopener"
              className="text-primary hover:underline break-all"
            >
              {config.repo_url}
            </a>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-muted-foreground min-w-[140px]">
              {t("settings.gitSync.config.branch")} :
            </span>
            <Badge variant="secondary">{config.branch}</Badge>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-muted-foreground min-w-[140px]">
              {t("settings.gitSync.config.authMode")} :
            </span>
            <Badge variant="secondary">
              {t(`settings.gitSync.config.authMode_${config.auth_mode}`)}
            </Badge>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-muted-foreground min-w-[140px]">
              {t("settings.gitSync.config.selectedTables")} :
            </span>
            <Badge variant="secondary">{config.selected_tables.length}</Badge>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-muted-foreground min-w-[140px]">
              {t("settings.gitSync.config.cron")} :
            </span>
            {config.cron_enabled && config.cron_expr ? (
              <Badge variant="default" className="font-mono">
                {config.cron_expr}
              </Badge>
            ) : (
              <Badge variant="outline">
                {t("settings.gitSync.config.cronDisabled")}
              </Badge>
            )}
          </div>
        </CardContent>
      </Card>

      <GitSyncConfigDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        initial={config}
      />

      <ConfirmDialog
        open={delOpen}
        onOpenChange={setDelOpen}
        title={t("settings.gitSync.config.deleteConfirmTitle")}
        description={t("settings.gitSync.config.deleteConfirm")}
        destructive
        onConfirm={handleDelete}
      />
    </>
  );
}
