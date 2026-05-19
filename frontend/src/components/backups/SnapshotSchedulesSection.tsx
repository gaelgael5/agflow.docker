import { useState } from "react";
import type { JSX } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronUp, Pencil, Play, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useQuery } from "@tanstack/react-query";

import { useSnapshotScheduleHistory, useSnapshotSchedules } from "@/hooks/useBackupSchedules";
import type {
  SnapshotScheduleSummary,
  CreateSnapshotPayload,
  UpdateSnapshotPayload,
} from "@/lib/backupSchedulesApi";
import type { Connection } from "@/components/backup-remotes/ConnectionModal";
import { api } from "@/lib/api";
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
import { ScheduleHistoryTable } from "./ScheduleHistoryTable";

// ─── Types ────────────────────────────────────────────────────────────────────

interface FormState {
  id?: string;
  name: string;
  interval_amount: number;
  interval_unit: "minutes" | "hours";
  retention_count: number;
  enabled: boolean;
  destination: "local" | "remote";
  remote_connection_id: string | null;
}

const EMPTY: FormState = {
  name: "",
  interval_amount: 15,
  interval_unit: "minutes",
  retention_count: 24,
  enabled: true,
  destination: "local",
  remote_connection_id: null,
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatInterval(amount: number, unit: "minutes" | "hours"): string {
  return `${amount} ${unit === "minutes" ? "min" : "h"}`;
}

function formatLastRun(
  s: SnapshotScheduleSummary,
  t: (k: string) => string,
): JSX.Element {
  if (!s.last_run_at) {
    return (
      <span className="text-muted-foreground">
        {t("backups.schedules.lastRunNever")}
      </span>
    );
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

function SnapshotHistoryPanel({ scheduleId }: { scheduleId: string }) {
  const { data, isLoading } = useSnapshotScheduleHistory(scheduleId, true);
  return <ScheduleHistoryTable entries={data} isLoading={isLoading} />;
}

// ─── Main component ───────────────────────────────────────────────────────────

export function SnapshotSchedulesSection() {
  const { t } = useTranslation();
  const { schedules, isLoading, create, update, remove, runNow, setEnabled } =
    useSnapshotSchedules();

  const { data: connections = [] } = useQuery<Connection[]>({
    queryKey: ["backup-remotes"],
    queryFn: () => api.get<Connection[]>("/admin/backup-remotes").then((r) => r.data),
  });

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [confirmDelete, setConfirmDelete] =
    useState<SnapshotScheduleSummary | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const openCreate = () => {
    setForm(EMPTY);
    setOpen(true);
  };

  const openEdit = (s: SnapshotScheduleSummary) => {
    setForm({
      id: s.id,
      name: s.name,
      interval_amount: s.interval_amount,
      interval_unit: s.interval_unit,
      retention_count: s.retention_count,
      enabled: s.enabled,
      destination: s.remote_connection_id ? "remote" : "local",
      remote_connection_id: s.remote_connection_id,
    });
    setOpen(true);
  };

  const handleSubmit = async () => {
    if (!form.name || form.interval_amount < 1) {
      toast.error(
        t("backups.schedules.runNowError", { msg: "invalid form" }),
      );
      return;
    }
    const remote_connection_id =
      form.destination === "remote" ? form.remote_connection_id : null;
    try {
      if (form.id) {
        const payload: UpdateSnapshotPayload = {
          name: form.name,
          interval_amount: form.interval_amount,
          interval_unit: form.interval_unit,
          retention_count: form.retention_count,
          enabled: form.enabled,
          remote_connection_id,
        };
        await update({ id: form.id, payload });
        toast.success(t("backups.schedules.updated"));
      } else {
        const payload: CreateSnapshotPayload = {
          name: form.name,
          interval_amount: form.interval_amount,
          interval_unit: form.interval_unit,
          retention_count: form.retention_count,
          enabled: form.enabled,
          remote_connection_id,
        };
        await create(payload);
        toast.success(t("backups.schedules.created"));
      }
      setOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  const handleRunNow = async (s: SnapshotScheduleSummary) => {
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

  const handleToggleEnabled = async (s: SnapshotScheduleSummary) => {
    try {
      await setEnabled({ id: s.id, enabled: !s.enabled });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  const isSubmitDisabled =
    !form.name ||
    form.interval_amount < 1 ||
    (form.destination === "remote" && !form.remote_connection_id) ||
    (form.destination === "remote" && connections.length === 0);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{t("backups.schedules.snapshotTitle")}</CardTitle>
        <Button onClick={openCreate}>{t("backups.schedules.addSnapshot")}</Button>
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
                <TableHead>{t("backups.schedules.colInterval")}</TableHead>
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
                    <TableCell className="font-mono text-xs">
                      {formatInterval(s.interval_amount, s.interval_unit)}
                    </TableCell>
                    <TableCell>{s.retention_count}</TableCell>
                    <TableCell>
                      {s.remote_connection_id ? (
                        <Badge variant="outline">
                          {connections.find((c) => c.id === s.remote_connection_id)?.name ??
                            "—"}
                        </Badge>
                      ) : (
                        <Badge variant="secondary">
                          {t("backups.schedules.destinationLocal")}
                        </Badge>
                      )}
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
                  {expandedId === s.id && (
                    <TableRow key={`${s.id}-history`}>
                      <TableCell colSpan={7} className="bg-muted/30 p-2">
                        <SnapshotHistoryPanel scheduleId={s.id} />
                      </TableCell>
                    </TableRow>
                  )}
                </>
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
              <Label htmlFor="snap-name">
                {t("backups.schedules.formNameLabel")}
              </Label>
              <Input
                id="snap-name"
                value={form.name}
                onChange={(e) =>
                  setForm((f) => ({ ...f, name: e.target.value }))
                }
                placeholder="snap-rapide"
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label htmlFor="snap-amount">
                  {t("backups.schedules.formIntervalAmount")}
                </Label>
                <Input
                  id="snap-amount"
                  type="number"
                  min={1}
                  value={form.interval_amount}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      interval_amount: parseInt(e.target.value, 10) || 1,
                    }))
                  }
                />
              </div>
              <div>
                <Label htmlFor="snap-unit">
                  {t("backups.schedules.formIntervalUnit")}
                </Label>
                <Select
                  value={form.interval_unit}
                  onValueChange={(v) =>
                    setForm((f) => ({
                      ...f,
                      interval_unit: v as "minutes" | "hours",
                    }))
                  }
                >
                  <SelectTrigger id="snap-unit">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="minutes">
                      {t("backups.schedules.formIntervalUnitMinutes")}
                    </SelectItem>
                    <SelectItem value="hours">
                      {t("backups.schedules.formIntervalUnitHours")}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <Label htmlFor="snap-retention">
                {t("backups.schedules.formRetentionLabel")}
              </Label>
              <Input
                id="snap-retention"
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
            <div>
              <Label htmlFor="snapshot-destination">
                {t("backups.schedules.formDestinationLabel")}
              </Label>
              <Select
                value={form.destination}
                onValueChange={(v) =>
                  setForm((f) => ({
                    ...f,
                    destination: v as "local" | "remote",
                    remote_connection_id: v === "local" ? null : f.remote_connection_id,
                  }))
                }
              >
                <SelectTrigger id="snapshot-destination">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="local">
                    {t("backups.schedules.destinationLocal")}
                  </SelectItem>
                  <SelectItem value="remote">
                    {t("backups.schedules.destinationRemote")}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            {form.destination === "remote" && (
              <div>
                <Label htmlFor="snapshot-remote-conn">
                  {t("backups.schedules.formRemoteConnectionLabel")}
                </Label>
                {connections.length === 0 ? (
                  <p className="text-xs text-destructive mt-1">
                    {t("backups.schedules.formRemoteConnectionNone")}
                  </p>
                ) : (
                  <Select
                    value={form.remote_connection_id ?? ""}
                    onValueChange={(v) =>
                      setForm((f) => ({ ...f, remote_connection_id: v || null }))
                    }
                  >
                    <SelectTrigger id="snapshot-remote-conn">
                      <SelectValue
                        placeholder={t("backups.schedules.formRemoteConnectionPlaceholder")}
                      />
                    </SelectTrigger>
                    <SelectContent>
                      {connections.map((c) => (
                        <SelectItem key={c.id} value={c.id}>
                          {c.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>
            )}
            <div className="flex items-center gap-2">
              <input
                id="snap-enabled"
                type="checkbox"
                checked={form.enabled}
                onChange={(e) =>
                  setForm((f) => ({ ...f, enabled: e.target.checked }))
                }
                className="h-4 w-4 rounded border-input"
              />
              <Label htmlFor="snap-enabled">
                {t("backups.schedules.formEnabledLabel")}
              </Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("backups.schedules.cancel")}
            </Button>
            <Button onClick={handleSubmit} disabled={isSubmitDisabled}>
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
