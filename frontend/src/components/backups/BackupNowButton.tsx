import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

export function BackupNowButton() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [running, setRunning] = useState(false);

  const handleClick = async () => {
    setRunning(true);
    try {
      await api.post("/admin/local-backups");
      toast.success(t("backups.backupNow.success"));
      // Refresh la liste des backups locaux
      qc.invalidateQueries({ queryKey: ["local-backups"] });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(t("backups.backupNow.error", { msg }));
    } finally {
      setRunning(false);
    }
  };

  return (
    <Button onClick={handleClick} disabled={running}>
      {running ? t("backups.backupNow.running") : t("backups.backupNow.button")}
    </Button>
  );
}
