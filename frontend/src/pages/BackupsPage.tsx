import { useTranslation } from "react-i18next";

import { BackupNowButton } from "@/components/backups/BackupNowButton";
import { FullSchedulesSection } from "@/components/backups/FullSchedulesSection";
import { LocalBackupsSection } from "@/components/backups/LocalBackupsSection";
import { PitrSection } from "@/components/backups/PitrSection";

export function BackupsPage() {
  const { t } = useTranslation();
  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold">{t("backups.page_title")}</h1>
          <p className="text-sm text-muted-foreground">
            {t("backups.page_subtitle")}
          </p>
        </div>
        <BackupNowButton />
      </div>

      <FullSchedulesSection />
      <LocalBackupsSection />
      <PitrSection />
    </div>
  );
}
