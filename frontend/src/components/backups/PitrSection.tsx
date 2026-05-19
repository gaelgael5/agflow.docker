import { useTranslation } from "react-i18next";

import { usePitrRestoreWindow } from "@/hooks/usePitr";

import { ActiveCloneCard } from "./ActiveCloneCard";
import { BasebackupsList } from "./BasebackupsList";
import { PitrConfigDialog } from "./PitrConfigDialog";
import { PitrRestoreForm } from "./PitrRestoreForm";
import { RecoveryWindowChart } from "./RecoveryWindowChart";
import { WalArchiveStatus } from "./WalArchiveStatus";

export function PitrSection() {
  const { t } = useTranslation();
  const { data: win } = usePitrRestoreWindow();
  return (
    <section className="space-y-4 border-t pt-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t("backups.pitr.title")}</h2>
        <PitrConfigDialog />
      </div>
      <WalArchiveStatus />
      <RecoveryWindowChart earliest={win?.earliest ?? null} latest={win?.latest ?? null} />
      <BasebackupsList />
      <PitrRestoreForm />
      <ActiveCloneCard />
    </section>
  );
}
