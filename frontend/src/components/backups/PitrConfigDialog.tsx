import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { type Connection } from "@/components/backup-remotes/ConnectionModal";
import { api } from "@/lib/api";
import { usePitrConfig } from "@/hooks/usePitr";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

export function PitrConfigDialog() {
  const { t } = useTranslation();
  const { data: cfg, update } = usePitrConfig();
  const remotes = useQuery<Connection[]>({
    queryKey: ["backup-remotes"],
    queryFn: () => api.get<Connection[]>("/admin/backup-remotes").then((r) => r.data),
  });

  const [open, setOpen] = useState(false);
  const [cron, setCron] = useState("");
  const [retention, setRetention] = useState(7);
  const [selectedRemotes, setSelectedRemotes] = useState<string[]>([]);
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    if (cfg) {
      setCron(cfg.basebackup_cron);
      setRetention(cfg.retention_count);
      setSelectedRemotes(cfg.remote_connection_ids);
      setEnabled(cfg.enabled);
    }
  }, [cfg]);

  const toggleRemote = (id: string) => {
    setSelectedRemotes((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const onSave = () => {
    update.mutate(
      {
        basebackup_cron: cron,
        retention_count: retention,
        remote_connection_ids: selectedRemotes,
        enabled,
      },
      { onSuccess: () => setOpen(false) }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm">
          ⚙ {t("backups.pitr.config.title")}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("backups.pitr.config.title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <label className="block">
            <span className="text-sm">{t("backups.pitr.config.cron")}</span>
            <input
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              className="mt-1 w-full rounded border px-2 py-1 font-mono"
              placeholder="0 3 * * *"
            />
          </label>
          <label className="block">
            <span className="text-sm">{t("backups.pitr.config.retention")}</span>
            <input
              type="number"
              min={1}
              value={retention}
              onChange={(e) =>
                setRetention(Math.max(1, Number.parseInt(e.target.value, 10) || 1))
              }
              className="mt-1 w-24 rounded border px-2 py-1"
            />
          </label>
          <div>
            <span className="text-sm">{t("backups.pitr.config.remotes")}</span>
            <div className="mt-1 max-h-40 space-y-1 overflow-y-auto">
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
                    {r.name} ({r.kind})
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
