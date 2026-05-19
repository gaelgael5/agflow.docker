import { useState } from "react";
import { useTranslation } from "react-i18next";

import { usePitrActiveClone, usePitrRestoreWindow } from "@/hooks/usePitr";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface DateTimeParts {
  date: string;
  time: string;
}

function localPartsFromUtcIso(iso: string): DateTimeParts {
  const d = new Date(iso);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return { date: `${yyyy}-${mm}-${dd}`, time: `${hh}:${mi}` };
}

function localPartsToUtcIso(date: string, time: string): string | null {
  if (!date || !time) return null;
  const local = new Date(`${date}T${time}:00`);
  if (Number.isNaN(local.getTime())) return null;
  return local.toISOString();
}

export function PitrRestoreForm() {
  const { t } = useTranslation();
  const { data: win } = usePitrRestoreWindow();
  const { start } = usePitrActiveClone();
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);

  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const min = win ? localPartsFromUtcIso(win.earliest) : null;
  const max = win ? localPartsFromUtcIso(win.latest) : null;
  const targetUtc = localPartsToUtcIso(date, time);
  const canSubmit = targetUtc !== null && win !== undefined && !start.isPending;

  const onConfirm = () => {
    if (targetUtc === null) return;
    start.mutate(targetUtc);
    setConfirmOpen(false);
    setDate("");
    setTime("");
  };

  return (
    <div className="space-y-2">
      <h4 className="font-semibold">{t("backups.pitr.restore.title")}</h4>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="block text-muted-foreground">
            {t("backups.pitr.restore.dateLabel")}
          </span>
          <input
            type="date"
            value={date}
            min={min?.date}
            max={max?.date}
            onChange={(e) => setDate(e.target.value)}
            className="mt-1 rounded border px-2 py-1"
          />
        </label>
        <label className="text-sm">
          <span className="block text-muted-foreground">
            {t("backups.pitr.restore.timeLabel")}
          </span>
          <input
            type="time"
            value={time}
            step={60}
            onChange={(e) => setTime(e.target.value)}
            className="mt-1 rounded border px-2 py-1"
          />
        </label>
        <Button disabled={!canSubmit} onClick={() => setConfirmOpen(true)}>
          {t("backups.pitr.restore.button")}
        </Button>
      </div>
      <p className="text-xs italic text-muted-foreground">
        {t("backups.pitr.restore.timezoneHint", { tz })}
        {targetUtc !== null && (
          <>
            {" · "}
            {t("backups.pitr.restore.utcPreview")} {targetUtc}
          </>
        )}
      </p>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t("backups.pitr.restore.confirmTitle", { date, time })}
            </DialogTitle>
            <DialogDescription>
              {t("backups.pitr.restore.confirmDescription")}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button onClick={onConfirm}>
              {t("backups.pitr.restore.launch")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
