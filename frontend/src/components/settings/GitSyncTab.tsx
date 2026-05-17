import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useGitSyncConfig } from "@/hooks/useGitSync";

import { GitSyncActionsSection } from "./GitSyncActionsSection";
import { GitSyncConfigDialog } from "./GitSyncConfigDialog";
import { GitSyncConfigSection } from "./GitSyncConfigSection";
import { GitSyncHistorySection } from "./GitSyncHistorySection";

export function GitSyncTab() {
  const { t } = useTranslation();
  const { data: config, isLoading } = useGitSyncConfig();
  const [createOpen, setCreateOpen] = useState(false);

  if (isLoading) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("common.loading", { defaultValue: "Chargement…" })}
      </p>
    );
  }

  if (!config) {
    return (
      <>
        <Card>
          <CardContent className="space-y-3 py-8 text-center">
            <p className="font-semibold">{t("settings.gitSync.empty.title")}</p>
            <p className="text-sm text-muted-foreground">
              {t("settings.gitSync.empty.subtitle")}
            </p>
            <Button onClick={() => setCreateOpen(true)}>
              {t("settings.gitSync.empty.cta")}
            </Button>
          </CardContent>
        </Card>
        <GitSyncConfigDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          initial={null}
        />
      </>
    );
  }

  return (
    <div className="space-y-4">
      <GitSyncConfigSection config={config} />
      <GitSyncActionsSection config={config} />
      <GitSyncHistorySection config={config} />
    </div>
  );
}
