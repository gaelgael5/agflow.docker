import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { backupsApi } from "@/lib/backupsApi";
import { Button } from "@/components/ui/button";

export function ScanImportButton() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [running, setRunning] = useState(false);

  const handleClick = async () => {
    setRunning(true);
    try {
      const result = await backupsApi.scanFromSchedules();
      if (result.errors.length > 0) {
        toast.warning(
          t("backups.scanImport.successWithErrors", {
            imported: result.imported,
            skipped: result.skipped,
            errorCount: result.errors.length,
          }),
        );
      } else {
        toast.success(
          t("backups.scanImport.success", {
            imported: result.imported,
            skipped: result.skipped,
          }),
        );
      }
      qc.invalidateQueries({ queryKey: ["local-backups"] });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(t("backups.scanImport.error", { msg }));
    } finally {
      setRunning(false);
    }
  };

  return (
    <Button variant="outline" onClick={handleClick} disabled={running}>
      {running ? t("backups.scanImport.running") : t("backups.scanImport.button")}
    </Button>
  );
}
