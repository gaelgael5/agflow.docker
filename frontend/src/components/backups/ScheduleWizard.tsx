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

export interface ScheduleWizardProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  mode: "create" | "edit";
  initialSchedule?: FullScheduleSummary;
  onSubmit: (payload: CreateFullPayload) => Promise<void>;
}

export function ScheduleWizard({
  open,
  onOpenChange,
  mode,
  initialSchedule,
  onSubmit,
}: ScheduleWizardProps) {
  const { t } = useTranslation();
  const remotesQuery = useQuery<Connection[]>({
    queryKey: ["backup-remotes"],
    queryFn: () => api.get<Connection[]>("/admin/backup-remotes").then((r) => r.data),
  });

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [recurrence, setRecurrence] = useState<RecurrenceType | null>(null);
  const [offset, setOffset] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [keepLocal, setKeepLocal] = useState(true);
  const [remoteConnectionIds, setRemoteConnectionIds] = useState<string[]>([]);
  const [retentionCount, setRetentionCount] = useState(10);
  const [cronFallback, setCronFallback] = useState<string | null>(null);

  useEffect(() => {
    if (mode === "edit" && initialSchedule) {
      setName(initialSchedule.name);
      setKeepLocal(initialSchedule.keep_local);
      setRemoteConnectionIds(initialSchedule.remote_connection_ids);
      setRetentionCount(initialSchedule.retention_count);
      const parsed = parseCron(initialSchedule.cron_expr);
      if (parsed) {
        setRecurrence(parsed.recurrence);
        setOffset(parsed.offset);
        setCronFallback(null);
      } else {
        setCronFallback(initialSchedule.cron_expr);
      }
    } else if (mode === "create" && open) {
      setStep(1);
      setRecurrence(null);
      setOffset(null);
      setName("");
      setKeepLocal(true);
      setRemoteConnectionIds([]);
      setRetentionCount(10);
      setCronFallback(null);
    }
  }, [mode, initialSchedule, open]);

  const canGoStep2 = recurrence !== null;
  const offsetMax = recurrence === "hourly" ? 59 : 23;
  const canGoStep3 = offset !== null && offset >= 0 && offset <= offsetMax;
  const hasDestination = keepLocal || remoteConnectionIds.length > 0;
  const canSubmit = name.trim().length > 0 && hasDestination;

  const toggleRemote = (id: string) => {
    setRemoteConnectionIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    const cron = cronFallback ?? buildCron(recurrence!, offset!);
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
              ? t("backups.wizard.title_create")
              : t("backups.wizard.title_edit")}
          </DialogTitle>
          <p className="text-xs text-muted-foreground">
            {t("backups.wizard.step_label", { current: step, total: 3 })}
          </p>
        </DialogHeader>

        {cronFallback ? (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              {t("backups.wizard.complexCron")} :{" "}
              <code className="font-mono">{cronFallback}</code>
            </p>
            <Label>{t("backups.wizard.editRaw")}</Label>
            <Input value={cronFallback} onChange={(e) => setCronFallback(e.target.value)} />
          </div>
        ) : (
          <>
            {step === 1 && (
              <div className="space-y-2">
                <Label>{t("backups.wizard.step1.title")}</Label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    checked={recurrence === "hourly"}
                    onChange={() => setRecurrence("hourly")}
                  />
                  {t("backups.wizard.step1.hourly")}
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    checked={recurrence === "daily"}
                    onChange={() => setRecurrence("daily")}
                  />
                  {t("backups.wizard.step1.daily")}
                </label>
              </div>
            )}

            {step === 2 && (
              <div className="space-y-2">
                <Label htmlFor="wizard-offset">
                  {recurrence === "hourly"
                    ? t("backups.wizard.step2.atMinute")
                    : t("backups.wizard.step2.atHour")}
                </Label>
                <Input
                  id="wizard-offset"
                  type="number"
                  min={0}
                  max={offsetMax}
                  value={offset ?? ""}
                  onChange={(e) =>
                    setOffset(e.target.value === "" ? null : parseInt(e.target.value, 10))
                  }
                />
                <p className="text-xs text-muted-foreground">
                  {recurrence === "hourly"
                    ? t("backups.wizard.step2.minuteHint")
                    : t("backups.wizard.step2.hourHint")}
                </p>
              </div>
            )}

            {step === 3 && (
              <div className="space-y-3">
                <div className="space-y-1">
                  <Label htmlFor="wizard-name">{t("backups.wizard.step3.name")}</Label>
                  <Input
                    id="wizard-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t("backups.wizard.step3.namePlaceholder")}
                  />
                </div>

                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={keepLocal}
                    onChange={(e) => setKeepLocal(e.target.checked)}
                  />
                  {t("backups.wizard.step3.keepLocal")}
                </label>

                <div className="space-y-1">
                  <Label>{t("backups.wizard.step3.remotes")}</Label>
                  <div className="max-h-40 space-y-1 overflow-y-auto rounded border p-2">
                    {remotesQuery.data?.length === 0 ? (
                      <p className="text-xs text-muted-foreground">
                        {t("backups.wizard.step3.noRemotes")}
                      </p>
                    ) : (
                      remotesQuery.data?.map((r) => (
                        <label key={r.id} className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={remoteConnectionIds.includes(r.id)}
                            onChange={() => toggleRemote(r.id)}
                          />
                          {r.name}{" "}
                          <span className="text-xs text-muted-foreground">({r.kind})</span>
                        </label>
                      ))
                    )}
                  </div>
                </div>

                <div className="space-y-1">
                  <Label htmlFor="wizard-retention">
                    {t("backups.wizard.step3.retention")}
                  </Label>
                  <Input
                    id="wizard-retention"
                    type="number"
                    min={1}
                    value={retentionCount}
                    onChange={(e) =>
                      setRetentionCount(Math.max(1, parseInt(e.target.value, 10) || 1))
                    }
                  />
                </div>

                {!hasDestination && (
                  <p className="text-xs text-destructive">
                    {t("backups.wizard.step3.errorNoDestination")}
                  </p>
                )}
              </div>
            )}
          </>
        )}

        <DialogFooter>
          {step > 1 && !cronFallback && (
            <Button variant="ghost" onClick={() => setStep((s) => (s - 1) as 1 | 2 | 3)}>
              {t("backups.wizard.prev")}
            </Button>
          )}
          {step === 1 && !cronFallback && (
            <Button disabled={!canGoStep2} onClick={() => setStep(2)}>
              {t("backups.wizard.next")}
            </Button>
          )}
          {step === 2 && !cronFallback && (
            <Button disabled={!canGoStep3} onClick={() => setStep(3)}>
              {t("backups.wizard.next")}
            </Button>
          )}
          {(step === 3 || cronFallback) && (
            <Button disabled={!canSubmit} onClick={handleSubmit}>
              {t("backups.wizard.save")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
