import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import {
  type CreateFullPayload,
  type FullScheduleSummary,
} from "@/lib/backupSchedulesApi";
import { buildCron, parseCron, type RecurrenceType } from "@/lib/cronWizard";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface Connection {
  id: string;
  name: string;
  kind: string;
}

type TestState = "idle" | "testing" | "ok" | "error";
interface TestResult { state: TestState; message?: string }

export interface ScheduleFormProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  mode: "create" | "edit";
  initialSchedule?: FullScheduleSummary;
  onSubmit: (payload: CreateFullPayload) => Promise<void>;
}

export function ScheduleForm({
  open,
  onOpenChange,
  mode,
  initialSchedule,
  onSubmit,
}: ScheduleFormProps) {
  const { t } = useTranslation();
  const remotesQuery = useQuery<Connection[]>({
    queryKey: ["backup-remotes"],
    queryFn: () => api.get<Connection[]>("/admin/backup-remotes").then((r) => r.data),
  });

  const [name, setName] = useState("");
  const [recurrence, setRecurrence] = useState<RecurrenceType>("daily");
  const [hour, setHour] = useState(0);
  const [minute, setMinute] = useState(0);
  const [keepLocal, setKeepLocal] = useState(true);
  const [remoteConnectionIds, setRemoteConnectionIds] = useState<string[]>([]);
  const [retentionCount, setRetentionCount] = useState(10);
  const [cronFallback, setCronFallback] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});

  useEffect(() => {
    if (mode === "edit" && initialSchedule) {
      setName(initialSchedule.name);
      setKeepLocal(initialSchedule.keep_local);
      setRemoteConnectionIds(initialSchedule.remote_connection_ids);
      setRetentionCount(initialSchedule.retention_count);
      const parsed = parseCron(initialSchedule.cron_expr);
      if (parsed) {
        setRecurrence(parsed.recurrence);
        setHour(parsed.hour);
        setMinute(parsed.minute);
        setCronFallback(null);
      } else {
        setCronFallback(initialSchedule.cron_expr);
      }
    } else if (mode === "create" && open) {
      setName("");
      setRecurrence("daily");
      setHour(0);
      setMinute(0);
      setKeepLocal(true);
      setRemoteConnectionIds([]);
      setRetentionCount(10);
      setCronFallback(null);
    }
    setTestResults({});
  }, [mode, initialSchedule, open]);

  const hasDestination = keepLocal || remoteConnectionIds.length > 0;
  const canSubmit = name.trim().length > 0 && hasDestination;

  const toggleRemote = (id: string) => {
    setRemoteConnectionIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const testWrite = async (id: string) => {
    setTestResults((prev) => ({ ...prev, [id]: { state: "testing" } }));
    try {
      const r = await api.post<{ ok: boolean; message?: string }>(
        `/admin/backup-remotes/${id}/test-write`,
      );
      setTestResults((prev) => ({
        ...prev,
        [id]: r.data.ok
          ? { state: "ok" }
          : { state: "error", message: r.data.message ?? t("common.error") },
      }));
    } catch (err) {
      setTestResults((prev) => ({
        ...prev,
        [id]: { state: "error", message: String(err) },
      }));
    }
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    const cron =
      cronFallback ??
      buildCron({ recurrence, hour, minute, dayOfWeek: 0, intervalN: 0 });
    await onSubmit({
      name,
      cron_expr: cron,
      remote_connection_ids: remoteConnectionIds,
      keep_local: keepLocal,
      retention_count: retentionCount,
      enabled: true,
    });
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {mode === "create"
              ? t("backups.form.title_create")
              : t("backups.form.title_edit")}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Nom — en haut */}
          <div className="space-y-1">
            <Label htmlFor="sf-name">{t("backups.form.name")}</Label>
            <Input
              id="sf-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("backups.form.namePlaceholder")}
            />
          </div>

          {cronFallback !== null ? (
            <div className="space-y-1">
              <Label htmlFor="sf-cron-raw">{t("backups.form.complexCron")}</Label>
              <Input
                id="sf-cron-raw"
                value={cronFallback}
                onChange={(e) => setCronFallback(e.target.value)}
                className="font-mono"
              />
              <p className="text-xs text-muted-foreground">
                {t("backups.form.complexCronHint")}
              </p>
            </div>
          ) : (
            <>
              {/* Fréquence */}
              <div className="space-y-2">
                <Label>{t("backups.form.frequency")}</Label>
                <div className="flex gap-4">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      checked={recurrence === "hourly"}
                      onChange={() => setRecurrence("hourly")}
                    />
                    {t("backups.form.hourly")}
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      checked={recurrence === "daily"}
                      onChange={() => setRecurrence("daily")}
                    />
                    {t("backups.form.daily")}
                  </label>
                </div>
              </div>

              {/* Moment HH:MM */}
              <div className="space-y-1">
                <Label>{t("backups.form.moment")}</Label>
                <div className="flex items-center gap-2">
                  {recurrence === "daily" && (
                    <>
                      <Input
                        type="number"
                        min={0}
                        max={23}
                        value={hour}
                        onChange={(e) =>
                          setHour(Math.min(23, Math.max(0, parseInt(e.target.value, 10) || 0)))
                        }
                        className="w-16 text-center"
                        aria-label={t("backups.form.hourField")}
                      />
                      <span className="font-mono text-lg">:</span>
                    </>
                  )}
                  <Input
                    type="number"
                    min={0}
                    max={59}
                    value={minute}
                    onChange={(e) =>
                      setMinute(Math.min(59, Math.max(0, parseInt(e.target.value, 10) || 0)))
                    }
                    className="w-16 text-center"
                    aria-label={t("backups.form.minuteField")}
                  />
                </div>
                <p className="text-xs text-muted-foreground">
                  {recurrence === "hourly"
                    ? t("backups.form.hourlyHint")
                    : t("backups.form.dailyHint")}
                </p>
              </div>
            </>
          )}

          {/* Conserver local */}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={keepLocal}
              onChange={(e) => setKeepLocal(e.target.checked)}
            />
            {t("backups.form.keepLocal")}
          </label>

          {/* Connexions distantes */}
          <div className="space-y-1">
            <Label>{t("backups.form.remotes")}</Label>
            <div className="max-h-40 space-y-1 overflow-y-auto rounded border p-2">
              {remotesQuery.data?.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  {t("backups.form.noRemotes")}
                </p>
              ) : (
                remotesQuery.data?.map((r) => {
                  const checked = remoteConnectionIds.includes(r.id);
                  const tr = testResults[r.id];
                  return (
                    <div key={r.id} className="flex items-center gap-2 text-sm">
                      <label className="flex flex-1 items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleRemote(r.id)}
                        />
                        {r.name}{" "}
                        <span className="text-xs text-muted-foreground">({r.kind})</span>
                      </label>
                      {checked && (
                        <>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-6 px-2 text-[10px]"
                            disabled={tr?.state === "testing"}
                            onClick={() => void testWrite(r.id)}
                          >
                            {tr?.state === "testing" ? "…" : t("backups.form.testWrite")}
                          </Button>
                          {tr?.state === "ok" && (
                            <span className="text-xs text-green-600">✓</span>
                          )}
                          {tr?.state === "error" && (
                            <span
                              className="text-xs text-destructive"
                              title={tr.message}
                            >
                              ✗
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Rétention */}
          <div className="space-y-1">
            <Label htmlFor="sf-retention">{t("backups.form.retention")}</Label>
            <Input
              id="sf-retention"
              type="number"
              min={1}
              value={retentionCount}
              onChange={(e) =>
                setRetentionCount(Math.max(1, parseInt(e.target.value, 10) || 1))
              }
              className="w-24"
            />
          </div>

          {!hasDestination && (
            <p className="text-xs text-destructive">
              {t("backups.form.errorNoDestination")}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button disabled={!canSubmit} onClick={handleSubmit}>
            {t("backups.form.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
