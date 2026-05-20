import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { type Connection } from "@/components/backup-remotes/ConnectionModal";
import { api } from "@/lib/api";
import { usePitrConfig } from "@/hooks/usePitr";
import { buildCron, parseCron, type RecurrenceType } from "@/lib/cronWizard";
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

export function PitrConfigDialog() {
  const { t } = useTranslation();
  const { data: cfg, update } = usePitrConfig();
  const remotes = useQuery<Connection[]>({
    queryKey: ["backup-remotes"],
    queryFn: () => api.get<Connection[]>("/admin/backup-remotes").then((r) => r.data),
  });

  const [open, setOpen] = useState(false);
  const [recurrence, setRecurrence] = useState<RecurrenceType>("daily");
  const [hour, setHour] = useState(0);
  const [minute, setMinute] = useState(0);
  const [cronFallback, setCronFallback] = useState<string | null>(null);
  const [selectedRemotes, setSelectedRemotes] = useState<string[]>([]);
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    if (!cfg) return;
    setSelectedRemotes(cfg.remote_connection_ids);
    setEnabled(cfg.enabled);
    const parsed = parseCron(cfg.basebackup_cron);
    if (parsed) {
      setRecurrence(parsed.recurrence);
      setHour(parsed.hour);
      setMinute(parsed.minute);
      setCronFallback(null);
    } else {
      setCronFallback(cfg.basebackup_cron);
    }
  }, [cfg]);

  const toggleRemote = (id: string) => {
    setSelectedRemotes((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const onSave = () => {
    const cron = cronFallback ?? buildCron({ recurrence, hour, minute });
    update.mutate(
      {
        basebackup_cron: cron,
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
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("backups.pitr.config.title")}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
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
                <Label>{t("backups.pitr.config.frequency")}</Label>
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
