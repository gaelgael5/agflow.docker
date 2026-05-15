import { useTranslation } from "react-i18next";

import { LocalBackupsSection } from "@/components/LocalBackupsSection";
import { RemoteBackupsBrowser } from "@/components/RemoteBackupsBrowser";

export function BackupsPage() {
  const { t } = useTranslation();
  return (
    <div className="space-y-8 p-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">{t("backups.page_title")}</h1>
        <p className="text-sm text-muted-foreground">
          {t("backups.page_subtitle")}
        </p>
      </header>
      <LocalBackupsSection />
      <RemoteBackupsBrowser />
    </div>
  );
}
