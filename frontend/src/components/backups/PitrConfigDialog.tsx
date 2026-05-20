import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { type Connection } from "@/components/backup-remotes/ConnectionModal";
import { api } from "@/lib/api";
import { usePitrConfig } from "@/hooks/usePitr";
import {
  buildCron,
  parseCron,
  type RecurrenceType,
} from "@/lib/cronWizard";
import type { BasebackupType } from "@/lib/pitrApi";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const DEFAULT_RETENTION = 7;
const DEFAULT_REBASE_CRON = "0 2 * * 0";
const BASEBACKUP_TYPES: BasebackupType[] = ["full", "diff", "incr"];

export function PitrConfigDialog() {
  const { t } = useTranslation();
  const { data: cfg, update } = usePitrConfig();
  const remotes = useQuery<Connection[]>({
    queryKey: ["backup-remotes"],
    queryFn: () => api.get<Connection[]>("/admin/backup-remotes").then((r) => r.data),
  });

  const [open, setOpen] = useState(false);
  const [basebackupType, setBasebackupType] = useState<BasebackupType>("diff");

  // Fréquence principale (cron des basebackups planifiés)
  const [recurrence, setRecurrence] = useState<RecurrenceType>("daily");
  const [hour, setHour] = useState(0);
  const [minute, setMinute] = useState(0);
  const [cronFallback, setCronFallback] = useState<string | null>(null);

  // Rebasage (cron du full hebdo) — utilisé uniquement si type ≠ full
  const [rebaseDayOfWeek, setRebaseDayOfWeek] = useState(0); // 0=dim
  const [rebaseHour, setRebaseHour] = useState(2);
  const [rebaseMinute, setRebaseMinute] = useState(0);
  const [rebaseFallback, setRebaseFallback] = useState<string | null>(null);

  const [selectedRemotes, setSelectedRemotes] = useState<string[]>([]);
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    if (!cfg) return;
    setBasebackupType(cfg.basebackup_type);
    setSelectedRemotes(cfg.remote_connection_ids);
    setEnabled(cfg.enabled);

    const parsed = parseCron(cfg.basebackup_cron);
    if (parsed && parsed.recurrence !== "weekly") {
      setRecurrence(parsed.recurrence);
      setHour(parsed.hour);
      setMinute(parsed.minute);
      setCronFallback(null);
    } else {
      setCronFallback(cfg.basebackup_cron);
    }

    const rebaseParsed = parseCron(cfg.full_rebase_cron);
    if (rebaseParsed && rebaseParsed.recurrence === "weekly") {
      setRebaseDayOfWeek(rebaseParsed.dayOfWeek);
      setRebaseHour(rebaseParsed.hour);
      setRebaseMinute(rebaseParsed.minute);
      setRebaseFallback(null);
    } else {
      setRebaseFallback(cfg.full_rebase_cron);
    }
  }, [cfg]);

  const toggleRemote = (id: string) => {
    setSelectedRemotes((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const onSave = () => {
    const cron =
      cronFallback ??
      buildCron({ recurrence, hour, minute, dayOfWeek: 0 });
    const rebaseCron =
      rebaseFallback ??
      buildCron({
        recurrence: "weekly",
        hour: rebaseHour,
        minute: rebaseMinute,
        dayOfWeek: rebaseDayOfWeek,
      });
    update.mutate(
      {
        basebackup_cron: cron,
        basebackup_type: basebackupType,
        full_rebase_cron: rebaseCron,
        retention_count: cfg?.retention_count ?? DEFAULT_RETENTION,
        remote_connection_ids: selectedRemotes,
        enabled,
      },
      { onSuccess: () => setOpen(false) },
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          {t("backups.pitr.config.configureButton")}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("backups.pitr.config.title")}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Section 1 : Type de basebackup */}
          <div className="space-y-2">
            <Label>{t("backups.pitr.config.basebackupType")}</Label>
            <div className="flex flex-col gap-1">
              {BASEBACKUP_TYPES.map((type) => (
                <label key={type} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    checked={basebackupType === type}
                    onChange={() => setBasebackupType(type)}
                  />
                  {t(`backups.pitr.config.type_${type}`)}
                </label>
              ))}
            </div>
            <p className="rounded border border-muted bg-muted/30 p-2 text-xs text-muted-foreground">
              {t(`backups.pitr.config.typeExplain_${basebackupType}`)}
            </p>
          </div>

          {/* Section 2 : Fréquence du basebackup planifié */}
          {cronFallback !== null ? (
            <div className="space-y-1">
              <Label htmlFor="pitr-cron-raw">
                {t("backups.pitr.config.complexCron")}
              </Label>
              <Input
                id="pitr-cron-raw"
                value={cronFallback}
                onChange={(e) => setCronFallback(e.target.value)}
                className="font-mono"
              />
              <p className="text-xs text-muted-foreground">
                {t("backups.pitr.config.complexCronHint")}
              </p>
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <Label>
                  {t("backups.pitr.config.frequencyFor", {
                    type: t(`backups.pitr.config.type_${basebackupType}`),
                  })}
                </Label>
                <div className="flex gap-4">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      checked={recurrence === "hourly"}
                      onChange={() => setRecurrence("hourly")}
                    />
                    {t("backups.pitr.config.hourly")}
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      checked={recurrence === "daily"}
                      onChange={() => setRecurrence("daily")}
                    />
                    {t("backups.pitr.config.daily")}
                  </label>
                </div>
              </div>

              <div className="space-y-1">
                <Label>{t("backups.pitr.config.moment")}</Label>
                <div className="flex items-center gap-2">
                  {recurrence === "daily" && (
                    <>
                      <Input
                        type="number"
                        min={0}
                        max={23}
                        value={hour}
                        onChange={(e) =>
                          setHour(
                            Math.min(23, Math.max(0, parseInt(e.target.value, 10) || 0)),
                          )
                        }
                        className="w-16 text-center"
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
                      setMinute(
                        Math.min(59, Math.max(0, parseInt(e.target.value, 10) || 0)),
                      )
                    }
                    className="w-16 text-center"
                  />
                </div>
                <p className="text-xs text-muted-foreground">
                  {recurrence === "hourly"
                    ? t("backups.pitr.config.hourlyHint")
                    : t("backups.pitr.config.dailyHint")}
                </p>
              </div>
            </>
          )}

          {/* Section 3 : Rebasage full hebdo (uniquement si type ≠ full) */}
          {basebackupType !== "full" && (
            <div className="rounded border border-dashed p-3 space-y-2">
              <Label>{t("backups.pitr.config.rebaseTitle")}</Label>
              <p className="text-xs text-muted-foreground">
                {t("backups.pitr.config.rebaseHint")}
              </p>
              {rebaseFallback !== null ? (
                <div className="space-y-1">
                  <Label htmlFor="pitr-rebase-raw">
                    {t("backups.pitr.config.complexCron")}
                  </Label>
                  <Input
                    id="pitr-rebase-raw"
                    value={rebaseFallback}
                    onChange={(e) => setRebaseFallback(e.target.value)}
                    className="font-mono"
                  />
                  <p className="text-xs text-muted-foreground">
                    {t("backups.pitr.config.complexCronHint")}
                  </p>
                </div>
              ) : (
                <div className="flex flex-wrap items-end gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">
                      {t("backups.pitr.config.rebaseDay")}
                    </Label>
                    <select
                      value={rebaseDayOfWeek}
                      onChange={(e) =>
                        setRebaseDayOfWeek(parseInt(e.target.value, 10))
                      }
                      className="h-9 rounded border bg-background px-2 text-sm"
                    >
                      {[0, 1, 2, 3, 4, 5, 6].map((d) => (
                        <option key={d} value={d}>
                          {t(`backups.pitr.config.day_${d}`)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">
                      {t("backups.pitr.config.rebaseTime")}
                    </Label>
                    <div className="flex items-center gap-2">
                      <Input
                        type="number"
                        min={0}
                        max={23}
                        value={rebaseHour}
                        onChange={(e) =>
                          setRebaseHour(
                            Math.min(23, Math.max(0, parseInt(e.target.value, 10) || 0)),
                          )
                        }
                        className="w-16 text-center"
                      />
                      <span className="font-mono text-lg">:</span>
                      <Input
                        type="number"
                        min={0}
                        max={59}
                        value={rebaseMinute}
                        onChange={(e) =>
                          setRebaseMinute(
                            Math.min(59, Math.max(0, parseInt(e.target.value, 10) || 0)),
                          )
                        }
                        className="w-16 text-center"
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Section 4 : Destinations */}
          <div className="space-y-1">
            <Label>{t("backups.pitr.config.remotes")}</Label>
            <div className="max-h-40 space-y-1 overflow-y-auto rounded border p-2">
              {remotes.data?.length === 0 ? (
                <p className="text-xs text-muted-foreground">—</p>
              ) : (
                remotes.data?.map((r) => (
                  <label key={r.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={selectedRemotes.includes(r.id)}
                      onChange={() => toggleRemote(r.id)}
                    />
                    {r.name}{" "}
                    <span className="text-xs text-muted-foreground">({r.kind})</span>
                  </label>
                ))
              )}
            </div>
          </div>

          {/* Section 5 : Activation */}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            {t("backups.pitr.config.enabled")}
          </label>

          <p className="rounded border border-muted bg-muted/30 p-2 text-xs text-muted-foreground">
            {t("backups.pitr.config.retentionAutoHint")}
          </p>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={onSave} disabled={update.isPending}>
            {t("backups.pitr.config.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Re-export so the dialog stays self-contained even if no one imports DEFAULT_REBASE_CRON.
export { DEFAULT_REBASE_CRON };
