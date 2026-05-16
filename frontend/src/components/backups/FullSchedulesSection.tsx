import type { JSX } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Pencil, Play, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { useFullSchedules } from "@/hooks/useBackupSchedules";
import type {
  FullScheduleSummary,
  CreateFullPayload,
  UpdateFullPayload,
} from "@/lib/backupSchedulesApi";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const PRESETS = [
  { key: "daily3am", expr: "0 3 * * *" },
  { key: "hourly", expr: "0 * * * *" },
  { key: "mondays", expr: "0 3 * * 1" },
  { key: "weekly", expr: "0 4 * * 0" },
] as const;

interface FormState {
  id?: string;
  name: string;
  cron_expr: string;
  retention_count: number;
  enabled: boolean;
}

const EMPTY: FormState = {
  name: "",
  cron_expr: "0 3 * * *",
  retention_count: 10,
  enabled: true,
};

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

export function FullSchedulesSection() {
  const { t } = useTranslation();
  const { schedules, isLoading, create, update, remove, runNow, setEnabled } =
    useFullSchedules();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [confirmDelete, setConfirmDelete] = useState<FullScheduleSummary | null>(null);

  const openCreate = () => {
    setForm(EMPTY);
    setOpen(true);
  };

  const openEdit = (s: FullScheduleSummary) => {
    setForm({
      id: s.id,
      name: s.name,
      cron_expr: s.cron_expr,
      retention_count: s.retention_count,
      enabled: s.enabled,
    });
    setOpen(true);
  };

  const handleSubmit = async () => {
    if (!form.name || !form.cron_expr) {
      toast.error(t("backups.schedules.runNowError", { msg: "name + cron required" }));
      return;
    }
    try {
      if (form.id) {
        const payload: UpdateFullPayload = {
          name: form.name,
          cron_expr: form.cron_expr,
          retention_count: form.retention_count,
          enabled: form.enabled,
        };
        await update({ id: form.id, payload });
        toast.success(t("backups.schedules.updated"));
      } else {
        const payload: CreateFullPayload = {
          name: form.name,
          cron_expr: form.cron_expr,
          retention_count: form.retention_count,
          enabled: form.enabled,
        };
        await create(payload);
        toast.success(t("backups.schedules.created"));
      }
      setOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

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
        <Button onClick={openCreate}>{t("backups.schedules.addFull")}</Button>
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
                <TableHead>{t("backups.schedules.colLastRun")}</TableHead>
                <TableHead>{t("backups.schedules.enabled")}</TableHead>
                <TableHead className="text-right">
                  {t("backups.schedules.colActions")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {schedules.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell className="font-mono text-xs">{s.cron_expr}</TableCell>
                  <TableCell>{s.retention_count}</TableCell>
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
                      onClick={() => handleRunNow(s)}
                      title={t("backups.schedules.runNow")}
                    >
                      <Play className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openEdit(s)}
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
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {form.id
                ? t("backups.schedules.editTitle")
                : t("backups.schedules.createTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="full-name">{t("backups.schedules.formNameLabel")}</Label>
              <Input
                id="full-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="db-quotidien"
              />
            </div>
            <div>
              <Label htmlFor="full-cron">{t("backups.schedules.formCronLabel")}</Label>
              <Input
                id="full-cron"
                value={form.cron_expr}
                onChange={(e) => setForm((f) => ({ ...f, cron_expr: e.target.value }))}
                placeholder="0 3 * * *"
                className="font-mono"
              />
              <p className="text-xs text-muted-foreground mt-1">
                {t("backups.schedules.formCronHint")}
              </p>
              <div className="flex gap-2 mt-2 flex-wrap">
                {PRESETS.map((p) => (
                  <Button
                    key={p.key}
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setForm((f) => ({ ...f, cron_expr: p.expr }))}
                  >
                    {t(`backups.schedules.cronPresets.${p.key}`)}
                  </Button>
                ))}
              </div>
            </div>
            <div>
              <Label htmlFor="full-retention">
                {t("backups.schedules.formRetentionLabel")}
              </Label>
              <Input
                id="full-retention"
                type="number"
                min={1}
                value={form.retention_count}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    retention_count: parseInt(e.target.value, 10) || 1,
                  }))
                }
              />
              <p className="text-xs text-muted-foreground mt-1">
                {t("backups.schedules.formRetentionHint")}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <input
                id="full-enabled"
                type="checkbox"
                checked={form.enabled}
                onChange={(e) =>
                  setForm((f) => ({ ...f, enabled: e.target.checked }))
                }
                className="h-4 w-4 rounded border-input"
              />
              <Label htmlFor="full-enabled">
                {t("backups.schedules.formEnabledLabel")}
              </Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("backups.schedules.cancel")}
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={!form.name || !form.cron_expr}
            >
              {t("backups.schedules.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
