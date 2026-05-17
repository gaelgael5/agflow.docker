import { useTranslation } from "react-i18next";

import { GitSyncTab } from "@/components/settings/GitSyncTab";
import { HarpocrateVaultsTab } from "@/components/settings/HarpocrateVaultsTab";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";

export function SettingsPage() {
  const { t } = useTranslation();

  return (
    <PageShell>
      <PageHeader
        title={t("settings.title")}
        subtitle={t("settings.description")}
      />
      <Tabs defaultValue="harpocrate" className="w-full">
        <TabsList>
          <TabsTrigger value="harpocrate">
            {t("settings.tabs.harpocrate")}
          </TabsTrigger>
          <TabsTrigger value="git-sync">
            {t("settings.tabs.gitSync")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="harpocrate" className="mt-4">
          <HarpocrateVaultsTab />
        </TabsContent>
        <TabsContent value="git-sync" className="mt-4">
          <GitSyncTab />
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}
