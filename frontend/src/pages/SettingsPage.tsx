import { useTranslation } from "react-i18next";

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
        </TabsList>
        <TabsContent value="harpocrate" className="mt-4">
          <HarpocrateVaultsTab />
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}
