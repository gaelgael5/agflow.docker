import type { JSX } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronUp, Pencil, Play, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useQuery } from "@tanstack/react-query";

import { useFullScheduleHistory, useFullSchedules } from "@/hooks/useBackupSchedules";
import type { FullScheduleSummary } from "@/lib/backupSchedulesApi";
import type { Connection } from "@/components/backup-remotes/ConnectionModal";
import { api } from "@/lib/api";
import { formatCronHuman } from "@/lib/cronWizard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ScheduleHistoryTable } from "./ScheduleHistoryTable";
import { ScheduleWizard } from "./ScheduleWizard";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatLastRun(s: FullScheduleSummary, t: (k: string) => string): JSX.Element {
  if (!s.last_run_at) {
    return <span className="text-muted-foreground">{t("backups.schedules.lastRunNever")}</span>;
  }
  const dt = new Date(s.last_run_at).toLocaleString();
  if (s.last_run_status === "ok") {
    return (
      <span className="text-xs">
        <Badge variant="default" className="mr-1">
          {t("backups.schedules.lastRunOk")}
        </Badge>
        {dt}
      </span>
    );
  }
  return (
    <span className="text-xs" title={s.last_run_error ?? ""}>
      <Badge variant="destructive" className="mr-1">
        {t("backups.schedules.lastRunFailed")}
      </Badge>
      {dt}
    </span>
  );
}

// ─── Inner components ─────────────────────────────────────────────────────────

function FullHistoryPanel({ scheduleId }: { scheduleId: string }) {
  const { data, isLoading } = useFullScheduleHistory(scheduleId, true);
  return <ScheduleHistoryTable entries={data} isLoading={isLoading} />;
}

// ─── Main component ───────────────────────────────────────────────────────────

export function FullSchedulesSection() {
  const { t } = useTranslation();
  const { schedules, isLoading, create, update, remove, runNow, setEnabled } =
    useFullSchedules();

  const { data: connections = [] } = useQuery<Connection[]>({
    queryKey: ["backup-remotes"],
    queryFn: () => api.get<Connection[]>("/admin/backup-remotes").then((r) => r.data),
  });

  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardMode, setWizardMode] = useState<"create" | "edit">("create");
  const [wizardSchedule, setWizardSchedule] = useState<FullScheduleSummary | undefined>(
    undefined,
  );
  const [confirmDelete, setConfirmDelete] = useState<FullScheduleSummary | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const handleRunNow = async (s: FullScheduleSummary) => {
    try {
      await runNow(s.id);
      toast.success(t("backups.schedules.runNowSuccess"));
    } catch (err) {
      toast.error(t("backups.schedules.runNowError", { msg: String(err) }));
    }
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    try {
      await remove(confirmDelete.id);
      toast.success(t("backups.schedules.deleted"));
      setConfirmDelete(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  const handleToggleEnabled = async (s: FullScheduleSummary) => {
    try {
      await setEnabled({ id: s.id, enabled: !s.enabled });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{t("backups.schedules.fullTitle")}</CardTitle>
        <Button
          onClick={() => {
            setWizardMode("create");
            setWizardSchedule(undefined);
            setWizardOpen(true);
          }}
        >
          {t("backups.schedules.addFull")}
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
        ) : schedules.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("backups.schedules.noneConfigured")}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("backups.schedules.colName")}</TableHead>
                <TableHead>{t("backups.schedules.colCron")}</TableHead>
                <TableHead>{t("backups.schedules.colRetention")}</TableHead>
                <TableHead>{t("backups.schedules.colDestination")}</TableHead>
                <TableHead>{t("backups.schedules.colLastRun")}</TableHead>
                <TableHead>{t("backups.schedules.enabled")}</TableHead>
                <TableHead className="text-right">
                  {t("backups.schedules.colActions")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {schedules.map((s) => (
                <>
                  <TableRow key={s.id}>
                    <TableCell className="font-medium">{s.name}</TableCell>
                    <TableCell className="text-xs">{formatCronHuman(s.cron_expr)}</TableCell>
                    <TableCell>{s.retention_count}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-1 text-xs">
                        {s.keep_local && (
                          <span className="rounded bg-muted px-1.5 py-0.5">
                            ✓ {t("backups.schedules.destinationLocalKept")}
                          </span>
                        )}
                        {s.remote_connection_ids.map((rid) => {
                          const r = connections.find((c) => c.id === rid);
                          return (
                            <span key={rid} className="rounded bg-muted px-1.5 py-0.5">
                              {r?.name ?? rid.slice(0, 8)}
                            </span>
                          );
                        })}
                        {!s.keep_local && s.remote_connection_ids.length === 0 && (
                          <span className="text-muted-foreground">
                            {t("backups.schedules.destinationLocalOnly")}
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>{formatLastRun(s, t)}</TableCell>
                    <TableCell>
                      <input
                        type="checkbox"
                        checked={s.enabled}
                        onChange={() => handleToggleEnabled(s)}
                        className="h-4 w-4 rounded border-input"
                        title={t("backups.schedules.toggleEnabled")}
                      />
                    </TableCell>
                    <TableCell className="text-right space-x-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setExpandedId(expandedId === s.id ? null : s.id)
                        }
                        title={
                          expandedId === s.id
                            ? t("backups.schedules.hideHistory")
                            : t("backups.schedules.viewHistory")
                        }
                      >
                        {expandedId === s.id ? (
                          <ChevronUp className="h-4 w-4" />
                        ) : (
                          <ChevronDown className="h-4 w-4" />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleRunNow(s)}
                        title={t("backups.schedules.runNow")}
                      >
                        <Play className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setWizardMode("edit");
                          setWizardSchedule(s);
                          setWizardOpen(true);
                        }}
                        title={t("common.edit")}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setConfirmDelete(s)}
                        title={t("common.delete")}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                  {expandedId === s.id && (
                    <TableRow key={`${s.id}-history`}>
                      <TableCell colSpan={7} className="bg-muted/30 p-2">
                        <FullHistoryPanel scheduleId={s.id} />
                      </TableCell>
                    </TableRow>
                  )}
                </>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <ScheduleWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        mode={wizardMode}
        initialSchedule={wizardSchedule}
        onSubmit={async (payload) => {
          if (wizardMode === "create") {
            await create(payload);
            toast.success(t("backups.schedules.created"));
          } else if (wizardSchedule) {
            await update({ id: wizardSchedule.id, payload });
            toast.success(t("backups.schedules.updated"));
          }
        }}
      />

      <ConfirmDialog
        open={confirmDelete !== null}
        onOpenChange={(o) => !o && setConfirmDelete(null)}
        title={t("backups.schedules.deleteConfirmTitle")}
        description={t("backups.schedules.deleteConfirmDescription", {
          name: confirmDelete?.name ?? "",
        })}
        confirmLabel={t("common.delete")}
        onConfirm={handleDelete}
      />
    </Card>
  );
}
